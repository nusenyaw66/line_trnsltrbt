"""Telegram spoken-voice gating, webhook payment hooks, and sendVoice path."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.pop("GEMINI_LIVE_TRANSLATE", None)

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("flask")

from gemini_voice import GeminiVoiceError  # noqa: E402
from telegram_payments import build_invoice_payload  # noqa: E402
from telegram_translator_bot import (  # noqa: E402
    _telegram_speech_to_text,
    app,
    handle_set_voice_command,
    handle_voice_message,
)

UTC = timezone.utc
WEBHOOK_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_set_voice_on_without_sub_does_not_enable():
    with patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=False
    ), patch("telegram_translator_bot.update_user_setting") as update, patch(
        "telegram_translator_bot._send_stars_invoice_link"
    ) as invoice, patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ):
        handle_set_voice_command("on", chat_id=1, user_id="42")
    update.assert_not_called()
    invoice.assert_called_once()
    assert invoice.call_args[0][3] == "voice_subscribe_required"


def test_set_voice_on_free_beta_enables_without_invoice():
    with patch("telegram_translator_bot.is_free_beta", return_value=True), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=False
    ), patch("telegram_translator_bot.grant_free_voice_subscription") as grant, patch(
        "telegram_translator_bot.update_user_setting"
    ) as update, patch(
        "telegram_translator_bot._send_stars_invoice_link"
    ) as invoice, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ):
        handle_set_voice_command("on", chat_id=1, user_id="42")
    grant.assert_called_once_with("42")
    update.assert_called_once_with("42", {"voice_enabled": True})
    invoice.assert_not_called()


def test_set_voice_on_with_sub_enables():
    with patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch("telegram_translator_bot.update_user_setting") as update, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ):
        handle_set_voice_command("on", chat_id=1, user_id="42")
    update.assert_called_once_with("42", {"voice_enabled": True})


def test_set_voice_gender_without_sub():
    with patch("telegram_translator_bot.update_user_setting") as update, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access"
    ) as access:
        handle_set_voice_command("male", chat_id=1, user_id="42")
    access.assert_not_called()
    update.assert_called_once_with("42", {"voice_gender": "male"})


def test_paid_voice_sends_voice_not_text():
    settings = {
        "enabled": True,
        "mode": "american",
        "voice_enabled": True,
        "voice_gender": "female",
        "source_lang": None,
        "target_lang": "en-US",
    }
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="Hello"
    ), patch(
        "telegram_translator_bot.speak_translation", return_value=b"opus"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ) as send_message, patch(
        "telegram_translator_bot.send_chat_action"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ), patch(
        "telegram_translator_bot.ai_voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    stt.assert_called()
    tts.assert_called_once()
    send_voice.assert_called_once()
    assert send_voice.call_args[0][1] == b"opus"
    send_message.assert_not_called()


def test_paid_tts_failure_does_not_send_text():
    settings = {
        "enabled": True,
        "mode": "american",
        "voice_enabled": True,
        "voice_gender": "female",
        "target_lang": "en-US",
    }
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="Hello"
    ), patch(
        "telegram_translator_bot.speak_translation",
        side_effect=GeminiVoiceError("boom"),
    ), patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ) as send_message, patch(
        "telegram_translator_bot.send_chat_action"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ), patch(
        "telegram_translator_bot.ai_voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    stt.assert_called()
    send_voice.assert_not_called()
    assert send_message.call_args[0][1] == "Spoken translation failed. Please try again."


def test_unpaid_voice_uses_stt_with_premium_access():
    settings = {
        "enabled": True,
        "mode": "american",
        "voice_enabled": False,
        "target_lang": "en-US",
    }
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=False
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot.speak_translation"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="hello"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    tts.assert_not_called()
    send_voice.assert_not_called()
    stt.assert_called()


def test_telegram_speech_to_text_passes_premium_access():
    with patch("telegram_translator_bot.speech_to_text") as stt:
        _telegram_speech_to_text(b"x", "en-US", alternative_language_codes=["ja-JP"])
    assert stt.call_args.kwargs["premium_access"] is True


def test_webhook_pre_checkout(client):
    with patch("telegram_translator_bot.WEBHOOK_SECRET", "test-secret"), patch(
        "telegram_translator_bot.handle_pre_checkout_query"
    ) as pre:
        resp = client.post(
            "/webhook",
            json={
                "pre_checkout_query": {
                    "id": "q1",
                    "from": {"id": 42},
                    "invoice_payload": build_invoice_payload("42"),
                }
            },
            headers=WEBHOOK_HEADERS,
        )
    assert resp.status_code == 200
    pre.assert_called_once()


def test_webhook_successful_payment(client):
    expiry = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    with patch("telegram_translator_bot.WEBHOOK_SECRET", "test-secret"), patch(
        "telegram_translator_bot.handle_successful_payment"
    ) as paid:
        resp = client.post(
            "/webhook",
            json={
                "message": {
                    "chat": {"id": 99, "type": "private"},
                    "from": {"id": 42},
                    "successful_payment": {
                        "invoice_payload": build_invoice_payload("42"),
                        "telegram_payment_charge_id": "chg",
                        "subscription_expiration_date": expiry,
                    },
                }
            },
            headers=WEBHOOK_HEADERS,
        )
    assert resp.status_code == 200
    paid.assert_called_once()
    assert paid.call_args[0][0] == "42"


def test_webhook_rejects_bad_secret(client):
    with patch("telegram_translator_bot.WEBHOOK_SECRET", "test-secret"):
        resp = client.post(
            "/webhook",
            json={"message": {}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
        )
    assert resp.status_code == 403


def _spoken_american_settings():
    return {
        "enabled": True,
        "mode": "american",
        "voice_enabled": True,
        "voice_gender": "female",
        "source_lang": None,
        "target_lang": "en-US",
    }


def test_live_translate_used_for_spoken_american(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "1")
    settings = _spoken_american_settings()
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot.live_translate_voice_note",
        return_value=(b"live-opus", "Hello there"),
    ) as live, patch(
        "telegram_translator_bot._telegram_speech_to_text"
    ) as stt, patch(
        "telegram_translator_bot.speak_translation"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ) as send_message, patch(
        "telegram_translator_bot.send_chat_action"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ), patch(
        "telegram_translator_bot.ai_voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    live.assert_called_once()
    stt.assert_not_called()
    tts.assert_not_called()
    send_voice.assert_called_once()
    assert send_voice.call_args[0][1] == b"live-opus"
    assert "Hello there" in send_voice.call_args[1]["caption"]
    send_message.assert_not_called()


def test_live_translate_skipped_for_pair_mode(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "1")
    settings = {
        "enabled": True,
        "mode": "pair",
        "voice_enabled": True,
        "voice_gender": "female",
        "source_lang": "en",
        "target_lang": "ja",
    }
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot.live_translate_voice_note"
    ) as live, patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="こんにちは"
    ), patch(
        "telegram_translator_bot.speak_translation", return_value=b"opus"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot.send_chat_action"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ), patch(
        "telegram_translator_bot.ai_voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    live.assert_not_called()
    stt.assert_called()
    tts.assert_called_once()
    send_voice.assert_called_once()


def test_live_translate_skipped_when_voice_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "1")
    settings = {
        "enabled": True,
        "mode": "american",
        "voice_enabled": False,
        "target_lang": "en-US",
    }
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=False
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot.live_translate_voice_note"
    ) as live, patch(
        "telegram_translator_bot.speak_translation"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ), patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="hello"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    live.assert_not_called()
    tts.assert_not_called()
    send_voice.assert_not_called()
    stt.assert_called()


def test_live_translate_failure_falls_back_to_stt_tts(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_TRANSLATE", "1")
    settings = _spoken_american_settings()
    with patch(
        "telegram_translator_bot.get_user_setting", return_value=settings
    ), patch(
        "telegram_translator_bot.telegram_has_voice_access", return_value=True
    ), patch(
        "telegram_translator_bot.download_telegram_audio", return_value=b"ogg"
    ), patch(
        "telegram_translator_bot.live_translate_voice_note",
        side_effect=GeminiVoiceError("live down"),
    ) as live, patch(
        "telegram_translator_bot._telegram_speech_to_text", return_value="hi"
    ) as stt, patch(
        "telegram_translator_bot.detect_and_translate", return_value="Hello"
    ), patch(
        "telegram_translator_bot.speak_translation", return_value=b"opus"
    ) as tts, patch(
        "telegram_translator_bot.send_voice"
    ) as send_voice, patch(
        "telegram_translator_bot.send_message"
    ) as send_message, patch(
        "telegram_translator_bot.send_chat_action"
    ), patch(
        "telegram_translator_bot._resolve_ui_lang", return_value="en"
    ), patch(
        "telegram_translator_bot.voice_rate_limiter.is_allowed", return_value=True
    ), patch(
        "telegram_translator_bot.ai_voice_rate_limiter.is_allowed", return_value=True
    ):
        handle_voice_message(1, "42", "file-1", {"id": 42, "first_name": "Ada"})
    live.assert_called_once()
    stt.assert_called()
    tts.assert_called_once()
    send_voice.assert_called_once()
    assert send_voice.call_args[0][1] == b"opus"
    send_message.assert_not_called()
