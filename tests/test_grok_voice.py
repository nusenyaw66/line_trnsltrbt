"""Tests for Grok TTS helpers and speak_translation wiring."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grok_voice
import gemini_voice


def test_grok_voice_id_defaults(monkeypatch):
    monkeypatch.delenv("GROK_VOICE_FEMALE", raising=False)
    monkeypatch.delenv("GROK_VOICE_MALE", raising=False)
    assert grok_voice.grok_voice_id("female") == "eve"
    assert grok_voice.grok_voice_id(None) == "eve"
    assert grok_voice.grok_voice_id("male") == "rex"


def test_grok_voice_id_env_override(monkeypatch):
    monkeypatch.setenv("GROK_VOICE_FEMALE", "ara")
    monkeypatch.setenv("GROK_VOICE_MALE", "leo")
    assert grok_voice.grok_voice_id("female") == "ara"
    assert grok_voice.grok_voice_id("male") == "leo"


def test_grok_language_code_from_mode():
    assert grok_voice.grok_language_code("american") == "en"
    assert grok_voice.grok_language_code("mandarin") == "zh"
    assert grok_voice.grok_language_code("japanese") == "ja"
    assert grok_voice.grok_language_code("pair") == "auto"
    assert grok_voice.grok_language_code(None) == "auto"


def test_grok_tts_bytes_posts_wav_request(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    captured = {}

    class _Resp:
        def read(self):
            return b"RIFFWAV"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=90):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Resp()

    with patch("grok_voice.urllib.request.urlopen", side_effect=fake_urlopen):
        audio = grok_voice.grok_tts_bytes("Hello", gender="male", language="en")
    assert audio == b"RIFFWAV"
    assert captured["url"] == "https://api.x.ai/v1/tts"
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["text"] == "Hello"
    assert captured["body"]["voice_id"] == "rex"
    assert captured["body"]["language"] == "en"
    assert captured["body"]["output_format"]["codec"] == "wav"


def test_grok_tts_bytes_requires_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(grok_voice.GrokVoiceError, match="XAI_API_KEY"):
        grok_voice.grok_tts_bytes("Hello")


def test_speak_translation_prefers_grok_when_key_set(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    with patch("grok_voice.grok_tts_ogg", return_value=b"grok-ogg") as grok, patch(
        "gemini_voice.synthesize_speech"
    ) as gemini_tts, patch("gemini_voice.understand_audio") as understand:
        ogg = gemini_voice.speak_translation("Hello", gender="female", mode="american")
    assert ogg == b"grok-ogg"
    grok.assert_called_once_with("Hello", gender="female", mode="american")
    gemini_tts.assert_not_called()
    understand.assert_not_called()


def test_speak_translation_grok_falls_back_to_cloud(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    with patch(
        "grok_voice.grok_tts_ogg",
        side_effect=grok_voice.GrokVoiceError("Grok TTS HTTP 401"),
    ), patch("gemini_voice.synthesize_speech") as gemini_tts, patch(
        "gemini_voice.cloud_tts_ogg", return_value=b"cloud-ogg"
    ) as cloud, patch("gemini_voice.understand_audio") as understand:
        ogg = gemini_voice.speak_translation("Hello", gender="male", mode="japanese")
    assert ogg == b"cloud-ogg"
    cloud.assert_called_once()
    gemini_tts.assert_not_called()
    understand.assert_not_called()
