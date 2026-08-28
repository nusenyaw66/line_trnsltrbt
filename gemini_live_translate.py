"""One-shot Gemini Live Translate for Telegram voice notes.

Telegram delivers a complete OGG after the user stops recording. This module
burst-sends that clip over the Live API WebSocket and returns translated OGG
Opus plus the output transcript for the caption.

Does not use GOOGLE_GEMINI_BASE_URL (REST generateContent proxies cannot carry
the v1alpha Live WebSocket).
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from gemini_voice import GeminiVoiceError, pcm_to_ogg_opus

DEFAULT_LIVE_MODEL = "gemini-3.5-live-translate-preview"
INPUT_PCM_RATE = 16000
OUTPUT_PCM_RATE = 24000
CHUNK_MS = 100
CHUNK_BYTES = INPUT_PCM_RATE * 2 * CHUNK_MS // 1000
TRAILING_SILENCE_MS = 300
SESSION_TIMEOUT_S = 120.0
IDLE_AFTER_AUDIO_S = 3.5

_FIXED_TARGET_MODES = {
    "american": "en",
    "mandarin": "zh-Hant",
    "japanese": "ja",
}


def live_translate_enabled() -> bool:
    """True when GEMINI_LIVE_TRANSLATE is an opt-in truthy value."""
    flag = (os.getenv("GEMINI_LIVE_TRANSLATE") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def live_translate_supported_mode(mode: Optional[str]) -> bool:
    """Live Translate is one target language; pair mode stays on STT+Translate."""
    return (mode or "").strip().lower() in _FIXED_TARGET_MODES


def target_language_code_for_mode(mode: Optional[str]) -> str:
    """Map bot mode to a Live Translate BCP-47 target language code."""
    key = (mode or "").strip().lower()
    if key not in _FIXED_TARGET_MODES:
        raise GeminiVoiceError(f"Live Translate does not support mode {mode!r}")
    return _FIXED_TARGET_MODES[key]


def live_connect_config(target_language_code: str, echo_target_language: bool = False) -> Any:
    """LiveConnectConfig for audio-to-audio translation plus transcripts."""
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        translation_config=types.TranslationConfig(
            target_language_code=target_language_code,
            echo_target_language=echo_target_language,
        ),
        # Burst-send of a finished Telegram clip is not real-time speech; VAD
        # would wait forever. Manual activity_start/end marks the utterance.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
        ),
    )


def ogg_to_pcm_s16le(audio_content: bytes, sample_rate: int = INPUT_PCM_RATE) -> bytes:
    """Decode OGG/Opus (or any ffmpeg-readable container) to s16le mono PCM."""
    if not audio_content:
        raise GeminiVoiceError("Empty audio")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "pipe:1",
        ],
        input=audio_content,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GeminiVoiceError(detail or "ffmpeg failed to decode audio to PCM")
    return proc.stdout


def _decode_audio_bytes(data: Any) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return base64.b64decode(data)
    return bytes(data)


def _pcm_from_response(response: Any) -> bytes:
    content = getattr(response, "server_content", None)
    if not content:
        return b""
    model_turn = getattr(content, "model_turn", None)
    if not model_turn:
        return b""
    pieces: list[bytes] = []
    for part in getattr(model_turn, "parts", None) or []:
        inline = getattr(part, "inline_data", None)
        raw = getattr(inline, "data", None) if inline is not None else None
        if raw:
            pieces.append(_decode_audio_bytes(raw))
    return b"".join(pieces)


def _transcript_delta(response: Any, attr: str) -> str:
    content = getattr(response, "server_content", None)
    if not content:
        return ""
    block = getattr(content, attr, None)
    text = getattr(block, "text", None) if block is not None else None
    return (text or "").strip()


def _transcript_finished(response: Any, attr: str) -> bool:
    content = getattr(response, "server_content", None)
    if not content:
        return False
    block = getattr(content, attr, None)
    return bool(getattr(block, "finished", False)) if block is not None else False


def _turn_done(response: Any) -> bool:
    content = getattr(response, "server_content", None)
    if not content:
        return False
    return bool(getattr(content, "turn_complete", False) or getattr(content, "generation_complete", False))


def _session_timeout_s() -> float:
    raw = (os.getenv("GEMINI_LIVE_TRANSLATE_TIMEOUT") or "").strip()
    if not raw:
        return SESSION_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return SESSION_TIMEOUT_S


def _live_client_and_model() -> Tuple[Any, str]:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or ""
    if not api_key:
        raise GeminiVoiceError("GEMINI_API_KEY is not set")
    client = genai.Client(
        api_key=api_key,
        vertexai=False,
        http_options=types.HttpOptions(api_version="v1alpha"),
    )
    model = os.getenv("GEMINI_LIVE_TRANSLATE_MODEL", DEFAULT_LIVE_MODEL).strip() or DEFAULT_LIVE_MODEL
    return client, model


def _default_connect(config: Any) -> Any:
    client, model = _live_client_and_model()
    return client.aio.live.connect(model=model, config=config)


def _iter_pcm_chunks(pcm: bytes) -> list[bytes]:
    chunks = [pcm[i : i + CHUNK_BYTES] for i in range(0, len(pcm), CHUNK_BYTES) if pcm[i : i + CHUNK_BYTES]]
    silence = b"\x00" * (INPUT_PCM_RATE * 2 * TRAILING_SILENCE_MS // 1000)
    if silence:
        chunks.append(silence)
    return chunks


async def translate_pcm(
    pcm: bytes,
    target_language_code: str,
    *,
    connect: Optional[Callable[[Any], Any]] = None,
    echo_target_language: bool = False,
    metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, str]:
    """Burst-send 16 kHz PCM; return 24 kHz PCM and output transcript."""
    if not pcm:
        raise GeminiVoiceError("Empty PCM")
    from google.genai import types

    stats = metrics if metrics is not None else {}
    started = time.perf_counter()
    config = live_connect_config(target_language_code, echo_target_language=echo_target_language)
    opener = connect or _default_connect

    pcm_out = bytearray()
    output_parts: list[str] = []
    input_parts: list[str] = []

    async with opener(config) as session:
        stats["connect_s"] = time.perf_counter() - started

        async def send_loop() -> None:
            await session.send_realtime_input(activity_start=types.ActivityStart())
            for chunk in _iter_pcm_chunks(pcm):
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={INPUT_PCM_RATE}")
                )
            await session.send_realtime_input(activity_end=types.ActivityEnd())
            await session.send_realtime_input(audio_stream_end=True)

        async def receive_loop() -> None:
            receiver = session.receive()
            audio_deadline: Optional[float] = None
            input_duration_s = len(pcm) / (INPUT_PCM_RATE * 2)
            max_output_s = max(input_duration_s * 4.0, 6.0)
            while True:
                now = time.perf_counter()
                if audio_deadline is not None and now >= audio_deadline:
                    break
                if pcm_out:
                    out_s = len(pcm_out) / (OUTPUT_PCM_RATE * 2)
                    if out_s >= max_output_s:
                        break
                if audio_deadline is None:
                    wait = _session_timeout_s()
                else:
                    wait = max(audio_deadline - now, 0.05)
                try:
                    response = await asyncio.wait_for(anext(receiver), timeout=wait)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if pcm_out:
                        break
                    raise GeminiVoiceError("Live Translate timed out waiting for translated audio")
                audio = _pcm_from_response(response)
                if audio:
                    if "first_audio_s" not in stats:
                        stats["first_audio_s"] = time.perf_counter() - started
                    pcm_out.extend(audio)
                    audio_deadline = time.perf_counter() + IDLE_AFTER_AUDIO_S
                in_text = _transcript_delta(response, "input_transcription")
                if in_text:
                    input_parts.append(in_text)
                out_text = _transcript_delta(response, "output_transcription")
                if out_text:
                    output_parts.append(out_text)
                    stats["transcript"] = "".join(output_parts).strip()
                if _turn_done(response) or (
                    pcm_out and _transcript_finished(response, "output_transcription")
                ):
                    break

        send_task = asyncio.create_task(send_loop())
        try:
            await asyncio.wait_for(receive_loop(), timeout=_session_timeout_s())
        except asyncio.TimeoutError:
            if not pcm_out:
                raise GeminiVoiceError("Live Translate timed out waiting for translated audio")
        finally:
            if not send_task.done():
                try:
                    await asyncio.wait_for(send_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    send_task.cancel()
                    try:
                        await send_task
                    except (asyncio.CancelledError, Exception):
                        pass

    stats["complete_s"] = time.perf_counter() - started
    stats["output_pcm_s"] = len(pcm_out) / (OUTPUT_PCM_RATE * 2) if pcm_out else 0.0
    transcript = "".join(output_parts).strip()
    stats["transcript"] = transcript
    stats["input_transcript"] = "".join(input_parts).strip()
    if not pcm_out:
        raise GeminiVoiceError("Live Translate returned no audio")
    return bytes(pcm_out), transcript


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    holder: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    thread = threading.Thread(target=_runner, name="gemini-live-translate")
    thread.start()
    thread.join()
    if "error" in holder:
        raise holder["error"]
    return holder["value"]


def live_translate_voice_note(
    audio_content: bytes,
    mode: Optional[str] = None,
    *,
    echo_target_language: bool = False,
    connect: Optional[Callable[[Any], Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, str]:
    """Voice note in → (OGG Opus translated speech, output transcript)."""
    target = target_language_code_for_mode(mode)
    pcm_in = ogg_to_pcm_s16le(audio_content)
    pcm_out, transcript = _run_sync(
        translate_pcm(
            pcm_in,
            target,
            connect=connect,
            echo_target_language=echo_target_language,
            metrics=metrics,
        )
    )
    if not (transcript or "").strip():
        raise GeminiVoiceError("Live Translate returned empty transcript")
    return pcm_to_ogg_opus(pcm_out, sample_rate=OUTPUT_PCM_RATE), transcript.strip()
