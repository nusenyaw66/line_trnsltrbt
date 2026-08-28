"""Unit tests for Gemini Live Translate one-shot helper (no live WebSocket)."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import gemini_live_translate as glt
from gemini_voice import GeminiVoiceError


def test_live_translate_enabled(monkeypatch):
    monkeypatch.delenv("GEMINI_LIVE_TRANSLATE", raising=False)
    assert glt.live_translate_enabled() is False
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "1")
    assert glt.live_translate_enabled() is True
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "true")
    assert glt.live_translate_enabled() is True
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "off")
    assert glt.live_translate_enabled() is False


def test_target_language_code_for_mode():
    assert glt.target_language_code_for_mode("american") == "en"
    assert glt.target_language_code_for_mode("mandarin") == "zh-Hant"
    assert glt.target_language_code_for_mode("japanese") == "ja"
    assert glt.live_translate_supported_mode("american") is True
    assert glt.live_translate_supported_mode("pair") is False
    with pytest.raises(GeminiVoiceError):
        glt.target_language_code_for_mode("pair")


def test_live_connect_config_maps_target():
    cfg = glt.live_connect_config("zh-Hant", echo_target_language=False)
    assert cfg.translation_config.target_language_code == "zh-Hant"
    assert cfg.translation_config.echo_target_language is False
    assert cfg.realtime_input_config.automatic_activity_detection.disabled is True


def test_ogg_to_pcm_uses_ffmpeg():
    completed = MagicMock(returncode=0, stdout=b"pcm", stderr=b"")
    with patch("gemini_live_translate.subprocess.run", return_value=completed) as run:
        out = glt.ogg_to_pcm_s16le(b"ogg-bytes", sample_rate=16000)
    assert out == b"pcm"
    args = run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "pcm_s16le" in args
    assert "16000" in args


def test_ogg_to_pcm_raises_on_empty():
    with pytest.raises(GeminiVoiceError):
        glt.ogg_to_pcm_s16le(b"")


def _event(*, pcm: bytes = b"", transcript: str = "", turn_complete: bool = False):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm) if pcm else None)
    return SimpleNamespace(
        server_content=SimpleNamespace(
            model_turn=SimpleNamespace(parts=[part]) if pcm else None,
            output_transcription=SimpleNamespace(text=transcript) if transcript else None,
            input_transcription=None,
            turn_complete=turn_complete,
            generation_complete=False,
        )
    )


class FakeSession:
    def __init__(self, events):
        self.events = events
        self.sent = []

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)

    async def receive(self):
        for event in self.events:
            yield event


class FakeConnect:
    def __init__(self, session: FakeSession):
        self.session = session
        self.config = None

    def __call__(self, config):
        self.config = config
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return None


def test_translate_pcm_assembles_audio_and_transcript():
    session = FakeSession(
        [
            _event(pcm=b"\x01\x02", transcript="Hel"),
            _event(pcm=b"\x03\x04", transcript="lo", turn_complete=True),
        ]
    )
    connect = FakeConnect(session)
    metrics: dict = {}
    pcm, text = glt._run_sync(
        glt.translate_pcm(b"\x00" * 64, "ja", connect=connect, metrics=metrics)
    )
    assert pcm == b"\x01\x02\x03\x04"
    assert text == "Hello"
    assert metrics["connect_s"] >= 0
    assert metrics["complete_s"] >= 0
    assert any("audio" in item for item in session.sent)
    assert any("activity_start" in item for item in session.sent)
    assert any("activity_end" in item for item in session.sent)
    assert any(item.get("audio_stream_end") is True for item in session.sent)
    assert connect.config.translation_config.target_language_code == "ja"


def test_translate_pcm_completes_without_turn_complete():
    session = FakeSession([_event(pcm=b"\x05\x06", transcript="Hi")])
    pcm, text = glt._run_sync(
        glt.translate_pcm(b"\x00" * 64, "en", connect=FakeConnect(session))
    )
    assert pcm == b"\x05\x06"
    assert text == "Hi"
    session = FakeSession([_event(transcript="hi", turn_complete=True)])
    with pytest.raises(GeminiVoiceError, match="no audio"):
        glt._run_sync(glt.translate_pcm(b"\x00" * 32, "en", connect=FakeConnect(session)))


def test_live_translate_voice_note_encodes_ogg_and_requires_transcript():
    session = FakeSession(
        [
            _event(pcm=b"\x01\x00", transcript="こんにちは", turn_complete=True),
        ]
    )
    with patch("gemini_live_translate.ogg_to_pcm_s16le", return_value=b"\x00" * 64), patch(
        "gemini_live_translate.pcm_to_ogg_opus", return_value=b"ogg-out"
    ) as encode:
        ogg, text = glt.live_translate_voice_note(
            b"fake-ogg",
            mode="japanese",
            connect=FakeConnect(session),
        )
    assert ogg == b"ogg-out"
    assert text == "こんにちは"
    encode.assert_called_once()
    assert encode.call_args.kwargs["sample_rate"] == glt.OUTPUT_PCM_RATE


def test_live_translate_voice_note_empty_transcript_falls_to_error():
    session = FakeSession([_event(pcm=b"\x01\x00", turn_complete=True)])
    with patch("gemini_live_translate.ogg_to_pcm_s16le", return_value=b"\x00" * 64):
        with pytest.raises(GeminiVoiceError, match="empty transcript"):
            glt.live_translate_voice_note(
                b"fake-ogg",
                mode="american",
                connect=FakeConnect(session),
            )
