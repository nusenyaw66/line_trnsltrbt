"""Tests for Gemini voice helpers (gender, prompts, two-hop wiring)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import gemini_voice


def test_voice_name_for_gender_defaults(monkeypatch):
    monkeypatch.delenv("GEMINI_VOICE_FEMALE", raising=False)
    monkeypatch.delenv("GEMINI_VOICE_MALE", raising=False)
    assert gemini_voice.voice_name_for_gender("female") == "Kore"
    assert gemini_voice.voice_name_for_gender(None) == "Kore"
    assert gemini_voice.voice_name_for_gender("male") == "Fenrir"


def test_voice_name_for_gender_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_VOICE_FEMALE", "Aoede")
    monkeypatch.setenv("GEMINI_VOICE_MALE", "Puck")
    assert gemini_voice.voice_name_for_gender("female") == "Aoede"
    assert gemini_voice.voice_name_for_gender("male") == "Puck"


def test_understand_prompt_fixed_modes():
    american = gemini_voice.build_understand_prompt("american")
    assert "American English" in american
    assert "ONLY the translation" in american
    assert "Traditional Chinese" in gemini_voice.build_understand_prompt("mandarin")
    assert "Japanese" in gemini_voice.build_understand_prompt("japanese")


def test_understand_prompt_pair_uses_other_language():
    prompt = gemini_voice.build_understand_prompt("pair", source_lang="en", target_lang="ja")
    assert "en" in prompt and "ja" in prompt
    assert "other language" in prompt


def test_extract_text_and_audio():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "  Hola  "},
                        {
                            "inlineData": {
                                "mimeType": "audio/L16;codec=pcm;rate=24000",
                                "data": "AQID",
                            }
                        },
                    ]
                }
            }
        ]
    }
    assert gemini_voice._extract_text(payload) == "Hola"
    audio, rate = gemini_voice._extract_audio(payload)
    assert audio == bytes([1, 2, 3])
    assert rate == 24000


def test_pcm_to_ogg_opus_uses_ffmpeg():
    completed = MagicMock(returncode=0, stdout=b"OGG", stderr=b"")
    with patch("gemini_voice.subprocess.run", return_value=completed) as run:
        out = gemini_voice.pcm_to_ogg_opus(b"pcm-bytes", sample_rate=24000)
    assert out == b"OGG"
    args = run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "libopus" in args


def test_pcm_to_ogg_opus_raises_on_empty():
    with pytest.raises(gemini_voice.GeminiVoiceError):
        gemini_voice.pcm_to_ogg_opus(b"")


def test_tts_language_key_from_mode():
    assert gemini_voice.tts_language_key("american") == "en-US"
    assert gemini_voice.tts_language_key("mandarin") == "zh-TW"
    assert gemini_voice.tts_language_key("japanese") == "ja"


def test_speak_translation_uses_cloud_without_xai(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with patch("gemini_voice.cloud_tts_ogg", return_value=b"cloud-ogg") as cloud, patch(
        "gemini_voice.synthesize_speech"
    ) as gemini_tts:
        ogg = gemini_voice.speak_translation("Hello", gender="female", mode="american")
    assert ogg == b"cloud-ogg"
    cloud.assert_called_once()
    gemini_tts.assert_not_called()
