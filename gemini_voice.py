"""Gemini helpers: Cloud TTS fallback and unused audio-in/TTS hops.

Spoken Telegram replies prefer Gemini Live Translate when enabled, then Grok/Cloud TTS.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_UNDERSTAND_MODEL = "gemini-3.6-flash"
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_MODEL_FALLBACKS = (
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
)
DEFAULT_VOICE_FEMALE = "Kore"
DEFAULT_VOICE_MALE = "Fenrir"
DEFAULT_PCM_RATE = 24000

# Cloud TTS language_code + Neural2/WaveNet name by gender.
_CLOUD_TTS_VOICES = {
    "en-US": {"female": ("en-US", "en-US-Neural2-F"), "male": ("en-US", "en-US-Neural2-D")},
    "en": {"female": ("en-US", "en-US-Neural2-F"), "male": ("en-US", "en-US-Neural2-D")},
    "zh-TW": {"female": ("cmn-TW", "cmn-TW-Wavenet-A"), "male": ("cmn-TW", "cmn-TW-Wavenet-B")},
    "zh-CN": {"female": ("cmn-CN", "cmn-CN-Wavenet-A"), "male": ("cmn-CN", "cmn-CN-Wavenet-B")},
    "ja": {"female": ("ja-JP", "ja-JP-Neural2-B"), "male": ("ja-JP", "ja-JP-Neural2-C")},
    "ja-JP": {"female": ("ja-JP", "ja-JP-Neural2-B"), "male": ("ja-JP", "ja-JP-Neural2-C")},
    "es": {"female": ("es-ES", "es-ES-Neural2-A"), "male": ("es-ES", "es-ES-Neural2-B")},
    "es-ES": {"female": ("es-ES", "es-ES-Neural2-A"), "male": ("es-ES", "es-ES-Neural2-B")},
    "th": {"female": ("th-TH", "th-TH-Standard-A"), "male": ("th-TH", "th-TH-Standard-A")},
    "id": {"female": ("id-ID", "id-ID-Wavenet-A"), "male": ("id-ID", "id-ID-Wavenet-B")},
    "fil": {"female": ("fil-PH", "fil-PH-Wavenet-A"), "male": ("fil-PH", "fil-PH-Wavenet-C")},
    "vi": {"female": ("vi-VN", "vi-VN-Wavenet-A"), "male": ("vi-VN", "vi-VN-Wavenet-B")},
    "fr": {"female": ("fr-FR", "fr-FR-Neural2-A"), "male": ("fr-FR", "fr-FR-Neural2-B")},
    "de": {"female": ("de-DE", "de-DE-Neural2-A"), "male": ("de-DE", "de-DE-Neural2-B")},
    "it": {"female": ("it-IT", "it-IT-Neural2-A"), "male": ("it-IT", "it-IT-Neural2-C")},
    "ko": {"female": ("ko-KR", "ko-KR-Neural2-A"), "male": ("ko-KR", "ko-KR-Neural2-C")},
}

_MODE_TARGETS = {
    "american": "American English",
    "mandarin": "Traditional Chinese as used in Taiwan (zh-TW)",
    "japanese": "Japanese",
}


class GeminiVoiceError(Exception):
    """Spoken translation failed (understand hop, TTS hop, or encoding)."""


def voice_name_for_gender(gender: Optional[str]) -> str:
    """Map male/female to a stable Gemini prebuilt voice name."""
    if (gender or "").strip().lower() == "male":
        return os.getenv("GEMINI_VOICE_MALE", DEFAULT_VOICE_MALE).strip() or DEFAULT_VOICE_MALE
    return os.getenv("GEMINI_VOICE_FEMALE", DEFAULT_VOICE_FEMALE).strip() or DEFAULT_VOICE_FEMALE


def build_understand_prompt(
    mode: Optional[str],
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
) -> str:
    """Short interpreter prompt: meaning-based translation, audio out as text only."""
    lines = [
        "You are a professional interpreter.",
        "Listen to the audio. Interpret meaning, not word-for-word.",
        "Keep names, numbers, and place names.",
        "Output ONLY the translation. No preamble, labels, quotes, or commentary.",
    ]
    normalized = (mode or "pair").strip().lower()
    if normalized in _MODE_TARGETS:
        lines.append(f"Always produce {_MODE_TARGETS[normalized]}.")
    else:
        src = source_lang or "language A"
        tgt = target_lang or "language B"
        lines.append(
            f"This conversation uses a language pair: {src} and {tgt}. "
            "Translate into the other language of the pair "
            "(whichever the speaker is not using)."
        )
    return " ".join(lines)


def _normalize_base_url(url: str) -> str:
    trimmed = url.strip().rstrip("/")
    for suffix in ("/v1beta", "/v1"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
    return trimmed.rstrip("/")


def tts_language_key(
    mode: Optional[str],
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    script: Optional[str] = None,
) -> str:
    """Pick a Cloud TTS catalog key from translation mode or detected script language."""
    normalized = (mode or "pair").strip().lower()
    if normalized == "american":
        return "en-US"
    if normalized == "mandarin":
        return "zh-TW"
    if normalized == "japanese":
        return "ja"
    if script:
        try:
            from gcs_translate import _get_client

            detected = (_get_client().detect_language(script) or {}).get("language") or ""
            key = _canonical_tts_key(detected)
            if key in _CLOUD_TTS_VOICES:
                return key
        except Exception as exc:
            print(f"WARNING: language detect for Cloud TTS failed: {exc}")
    return _canonical_tts_key(target_lang or source_lang or "en-US")


def _canonical_tts_key(code: Optional[str]) -> str:
    raw = (code or "en-US").strip()
    lowered = raw.lower().replace("_", "-")
    aliases = {
        "en": "en-US",
        "en-us": "en-US",
        "zh-tw": "zh-TW",
        "zh-hant": "zh-TW",
        "cmn-tw": "zh-TW",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "cmn-cn": "zh-CN",
        "ja": "ja",
        "ja-jp": "ja",
        "jpn": "ja",
    }
    if lowered in aliases:
        return aliases[lowered]
    for key in _CLOUD_TTS_VOICES:
        if key.lower() == lowered:
            return key
    primary = lowered.split("-")[0]
    return aliases.get(primary, "en-US")


def cloud_tts_ogg(
    text: str,
    gender: Optional[str] = None,
    mode: Optional[str] = None,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
) -> bytes:
    """Speak ``text`` with Cloud TTS as OGG Opus (Telegram sendVoice)."""
    from google.cloud import texttospeech_v1

    script = (text or "").strip()
    if not script:
        raise GeminiVoiceError("Empty translation script")
    key = tts_language_key(mode, source_lang, target_lang, script)
    pair = _CLOUD_TTS_VOICES.get(key) or _CLOUD_TTS_VOICES["en-US"]
    slot = "male" if (gender or "").strip().lower() == "male" else "female"
    language_code, voice_name = pair[slot]
    ssml_gender = (
        texttospeech_v1.SsmlVoiceGender.MALE
        if slot == "male"
        else texttospeech_v1.SsmlVoiceGender.FEMALE
    )
    client = texttospeech_v1.TextToSpeechClient()
    voice = texttospeech_v1.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
        ssml_gender=ssml_gender,
    )
    audio_config = texttospeech_v1.AudioConfig(
        audio_encoding=texttospeech_v1.AudioEncoding.OGG_OPUS,
    )
    try:
        response = client.synthesize_speech(
            input=texttospeech_v1.SynthesisInput(text=script),
            voice=voice,
            audio_config=audio_config,
        )
    except Exception as exc:
        print(f"WARNING: named Cloud TTS voice {voice_name} failed: {exc}")
        voice = texttospeech_v1.VoiceSelectionParams(
            language_code=language_code,
            ssml_gender=ssml_gender,
        )
        response = client.synthesize_speech(
            input=texttospeech_v1.SynthesisInput(text=script),
            voice=voice,
            audio_config=audio_config,
        )
    if not response.audio_content:
        raise GeminiVoiceError("Cloud TTS returned empty audio")
    return response.audio_content


def _parse_pcm_rate(mime_type: Optional[str]) -> int:
    if not mime_type:
        return DEFAULT_PCM_RATE
    for part in mime_type.split(";"):
        piece = part.strip().lower()
        if piece.startswith("rate="):
            try:
                return int(piece.split("=", 1)[1])
            except ValueError:
                return DEFAULT_PCM_RATE
    return DEFAULT_PCM_RATE


def pcm_to_ogg_opus(
    pcm: bytes,
    sample_rate: int = DEFAULT_PCM_RATE,
    channels: int = 1,
) -> bytes:
    """Convert s16le PCM to OGG Opus via ffmpeg."""
    if not pcm:
        raise GeminiVoiceError("TTS returned empty audio")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
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
        input=pcm,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise GeminiVoiceError(detail or "ffmpeg failed to encode OGG Opus")
    return proc.stdout


def _decode_inline_bytes(data: Any) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return base64.b64decode(data)
    return bytes(data)


def _extract_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    texts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _extract_audio(payload: Dict[str, Any]) -> Tuple[bytes, int]:
    candidates = payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            raw = inline.get("data")
            if raw:
                mime = inline.get("mimeType") or inline.get("mime_type")
                return _decode_inline_bytes(raw), _parse_pcm_rate(mime)
    raise GeminiVoiceError("TTS response contained no audio")


def _sdk_generate_content(model: str, body: Dict[str, Any]) -> Dict[str, Any]:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or ""
    base_url = os.getenv("GOOGLE_GEMINI_BASE_URL") or ""
    kwargs: Dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["http_options"] = types.HttpOptions(base_url=_normalize_base_url(base_url))
    client = genai.Client(**kwargs)
    contents = body.get("contents")
    gen = body.get("generationConfig") or {}
    config = None
    if gen:
        cfg_kwargs: Dict[str, Any] = {}
        modalities = gen.get("responseModalities") or gen.get("response_modalities")
        if modalities:
            cfg_kwargs["response_modalities"] = modalities
        speech = gen.get("speechConfig") or gen.get("speech_config") or {}
        voice_cfg = speech.get("voiceConfig") or speech.get("voice_config") or {}
        prebuilt = voice_cfg.get("prebuiltVoiceConfig") or voice_cfg.get("prebuilt_voice_config") or {}
        voice_name = prebuilt.get("voiceName") or prebuilt.get("voice_name")
        if voice_name:
            cfg_kwargs["speech_config"] = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            )
        if cfg_kwargs:
            config = types.GenerateContentConfig(**cfg_kwargs)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    return response.model_dump(mode="json") if hasattr(response, "model_dump") else json.loads(
        response.model_dump_json()
    )


def _rest_generate_content(model: str, body: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or ""
    if not api_key:
        raise GeminiVoiceError("GEMINI_API_KEY is not set")
    base = _normalize_base_url(os.getenv("GOOGLE_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com")
    url = f"{base}/v1beta/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    # Proxies often want Bearer; Google AI Studio rejects Bearer API keys (expects x-goog-api-key).
    if os.getenv("GOOGLE_GEMINI_BASE_URL"):
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise GeminiVoiceError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise GeminiVoiceError(str(exc)) from exc


def generate_content(model: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Call Gemini generateContent. Prefer REST when a proxy base URL is set."""
    if os.getenv("GOOGLE_GEMINI_BASE_URL"):
        try:
            return _rest_generate_content(model, body)
        except GeminiVoiceError:
            raise
        except Exception as exc:
            print(f"WARNING: Gemini REST generateContent failed, trying SDK: {exc}")
            return _sdk_generate_content(model, body)
    try:
        return _sdk_generate_content(model, body)
    except GeminiVoiceError:
        raise
    except Exception as exc:
        print(f"WARNING: google-genai SDK generateContent failed, using REST: {exc}")
        return _rest_generate_content(model, body)


def understand_audio(
    audio_content: bytes,
    mime_type: str = "audio/ogg",
    mode: Optional[str] = None,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
) -> str:
    """Audio in → translated script (text)."""
    if not audio_content:
        raise GeminiVoiceError("Empty audio")
    model = os.getenv("GEMINI_UNDERSTAND_MODEL", DEFAULT_UNDERSTAND_MODEL).strip() or DEFAULT_UNDERSTAND_MODEL
    prompt = build_understand_prompt(mode, source_lang, target_lang)
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64.b64encode(audio_content).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ],
            }
        ]
    }
    payload = generate_content(model, body)
    text = _extract_text(payload)
    if not text:
        raise GeminiVoiceError("Gemini returned no translation")
    return text


def synthesize_speech(text: str, gender: Optional[str] = None) -> Tuple[bytes, int]:
    """Text in → PCM audio and sample rate."""
    script = (text or "").strip()
    if not script:
        raise GeminiVoiceError("Empty translation script")
    requested = os.getenv("GEMINI_TTS_MODEL", DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL
    models: list[str] = []
    for name in (requested, *TTS_MODEL_FALLBACKS):
        if name and name not in models:
            models.append(name)
    last_error: Optional[Exception] = None
    for model in models:
        voice_name = voice_name_for_gender(gender)
        body = {
            "contents": [{"role": "user", "parts": [{"text": script}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name}
                    }
                },
            },
        }
        try:
            payload = generate_content(model, body)
            return _extract_audio(payload)
        except Exception as exc:
            last_error = exc
            print(f"WARNING: Gemini TTS model {model} failed: {exc}")
    raise GeminiVoiceError(str(last_error) if last_error else "Gemini TTS failed")


def _cloud_tts_fallback(
    script: str,
    gender: Optional[str],
    mode: Optional[str],
    source_lang: Optional[str],
    target_lang: Optional[str],
    reason: str,
) -> bytes:
    print(f"WARNING: {reason}; using Cloud Text-to-Speech")
    return cloud_tts_ogg(
        script,
        gender=gender,
        mode=mode,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def speak_translation(
    script: str,
    gender: Optional[str] = None,
    mode: Optional[str] = None,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
) -> bytes:
    """Speak an already-translated script: Grok TTS, else Cloud TTS. No Gemini."""
    text = (script or "").strip()
    if not text:
        raise GeminiVoiceError("Empty translation script")
    if os.getenv("XAI_API_KEY"):
        from grok_voice import GrokVoiceError, grok_tts_ogg

        try:
            return grok_tts_ogg(text, gender=gender, mode=mode)
        except GrokVoiceError as exc:
            return _cloud_tts_fallback(
                text, gender, mode, source_lang, target_lang, f"Grok TTS unavailable ({exc})"
            )
    return cloud_tts_ogg(
        text,
        gender=gender,
        mode=mode,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def smoke_test_proxy() -> Dict[str, Any]:
    """Tiny generateContent call to verify API key + base URL. No audio required."""
    model = os.getenv("GEMINI_UNDERSTAND_MODEL", DEFAULT_UNDERSTAND_MODEL).strip() or DEFAULT_UNDERSTAND_MODEL
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with the single word: ok"}]}]
    }
    payload = generate_content(model, body)
    text = _extract_text(payload)
    return {"ok": bool(text), "text": text, "model": model}
