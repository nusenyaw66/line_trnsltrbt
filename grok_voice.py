"""xAI Grok TTS for Telegram spoken replies.

Think Fast 2.0 (grok-voice-think-fast-2.0) is a live WebSocket speech-to-speech
agent. Telegram voice notes are one-shot, so we speak the translated script via
POST https://api.x.ai/v1/tts using the same Grok voice IDs (eve, rex, …).
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Optional

DEFAULT_TTS_URL = "https://api.x.ai/v1/tts"
DEFAULT_VOICE_FEMALE = "eve"
DEFAULT_VOICE_MALE = "rex"
DEFAULT_SAMPLE_RATE = 24000
MAX_TTS_CHARS = 15000


class GrokVoiceError(Exception):
    """Grok TTS failed."""


def grok_voice_id(gender: Optional[str]) -> str:
    """Map male/female to a Grok TTS voice id."""
    if (gender or "").strip().lower() == "male":
        return os.getenv("GROK_VOICE_MALE", DEFAULT_VOICE_MALE).strip() or DEFAULT_VOICE_MALE
    return os.getenv("GROK_VOICE_FEMALE", DEFAULT_VOICE_FEMALE).strip() or DEFAULT_VOICE_FEMALE


def grok_language_code(mode: Optional[str]) -> str:
    """BCP-47-ish language for xAI TTS. Pair mode uses auto-detect."""
    normalized = (mode or "pair").strip().lower()
    if normalized == "american":
        return "en"
    if normalized == "mandarin":
        return "zh"
    if normalized == "japanese":
        return "ja"
    return "auto"


def encoded_audio_to_ogg_opus(audio: bytes) -> bytes:
    """Convert WAV/MP3 (or any ffmpeg-readable container) to OGG Opus."""
    if not audio:
        raise GrokVoiceError("Grok TTS returned empty audio")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-f",
            "ogg",
            "pipe:1",
        ],
        input=audio,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GrokVoiceError(detail or "ffmpeg failed to encode OGG Opus")
    return proc.stdout


def grok_tts_bytes(
    text: str,
    gender: Optional[str] = None,
    language: str = "auto",
) -> bytes:
    """Speak ``text`` with Grok TTS. Returns WAV (or MP3) bytes."""
    script = (text or "").strip()
    if not script:
        raise GrokVoiceError("Empty translation script")
    api_key = os.getenv("XAI_API_KEY") or ""
    if not api_key:
        raise GrokVoiceError("XAI_API_KEY is not set")
    url = (os.getenv("XAI_TTS_URL") or DEFAULT_TTS_URL).strip() or DEFAULT_TTS_URL
    body = {
        "text": script[:MAX_TTS_CHARS],
        "voice_id": grok_voice_id(gender),
        "language": language or "auto",
        "output_format": {
            "codec": "wav",
            "sample_rate": DEFAULT_SAMPLE_RATE,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise GrokVoiceError(f"Grok TTS HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise GrokVoiceError(str(exc)) from exc
    if not audio:
        raise GrokVoiceError("Grok TTS returned empty audio")
    return audio


def grok_tts_ogg(
    text: str,
    gender: Optional[str] = None,
    mode: Optional[str] = None,
) -> bytes:
    """Speak ``text`` as OGG Opus for Telegram sendVoice."""
    wav = grok_tts_bytes(text, gender=gender, language=grok_language_code(mode))
    return encoded_audio_to_ogg_opus(wav)
