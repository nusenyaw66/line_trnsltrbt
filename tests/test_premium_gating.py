"""Tests for premium feature gating (Task 3)."""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

pytest.importorskip("flask")
pytest.importorskip("linebot")

from gcs_audio import PremiumRequiredError, speech_to_text, text_to_speech  # noqa: E402
from gcs_translate import PremiumRequiredError as TranslatePremiumRequiredError  # noqa: E402
from gcs_translate import detect_and_translate  # noqa: E402
from premium_gating import (  # noqa: E402
    is_ai_translation_mode,
    requires_premium_for_translation,
    requires_premium_for_voice,
)
from subscription_access import has_premium_access  # noqa: E402

UTC = timezone.utc
FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


# ---------- has_premium_access (Task 2 dependency) ----------


def test_has_premium_access_true_for_active_personal_subscription():
    settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert has_premium_access("U123", settings) is True


def test_has_premium_access_false_without_subscription():
    assert has_premium_access("U123", {}) is False


def test_has_premium_access_true_for_active_group_subscription():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert has_premium_access("U999", user_settings, group_id="G456", group_settings=group_settings) is True


def test_has_premium_access_false_for_expired_subscription():
    settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
    }
    assert has_premium_access("U123", settings, at=datetime(2021, 1, 1, tzinfo=UTC)) is False


# ---------- premium_gating helpers ----------


@pytest.mark.parametrize("mode", ["american", "mandarin", "japanese"])
def test_is_ai_translation_mode(mode):
    assert is_ai_translation_mode(mode) is True


def test_is_ai_translation_mode_false_for_pair():
    assert is_ai_translation_mode("pair") is False


def test_requires_premium_for_translation_only_for_ai_modes():
    assert requires_premium_for_translation("american", enabled=True) is True
    assert requires_premium_for_translation("pair", enabled=True) is False
    assert requires_premium_for_translation("american", enabled=False) is False


def test_requires_premium_for_voice():
    assert requires_premium_for_voice() is True


# ---------- gcs_translate AI path ----------


def test_detect_and_translate_blocks_ai_mode_without_premium():
    with pytest.raises(TranslatePremiumRequiredError):
        detect_and_translate(
            "hello",
            enabled=True,
            mode="american",
            premium_access=False,
        )


def test_detect_and_translate_allows_pair_mode_without_premium():
    with patch("gcs_translate._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.detect_language.return_value = {"language": "en"}
        mock_client.translate.return_value = {"translatedText": "你好"}
        mock_get_client.return_value = mock_client

        result = detect_and_translate(
            "hello",
            enabled=True,
            source_lang="en",
            target_lang="zh-TW",
            mode="pair",
            premium_access=False,
        )

    assert result == "你好"


def test_detect_and_translate_allows_ai_mode_with_premium():
    with patch("gcs_translate._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.detect_language.return_value = {"language": "zh-TW"}
        mock_get_client.return_value = mock_client

        with patch("gcs_translate.translate_text", return_value="hello") as mock_translate:
            result = detect_and_translate(
                "你好",
                enabled=True,
                mode="american",
                premium_access=True,
            )

    mock_translate.assert_called_once_with("你好", "en-US")
    assert result == "hello"


# ---------- gcs_audio STT/TTS paths ----------


def test_speech_to_text_requires_premium_access():
    with pytest.raises(PremiumRequiredError):
        speech_to_text(b"audio", "en-US", premium_access=False)


def test_text_to_speech_requires_premium_access():
    with pytest.raises(PremiumRequiredError):
        text_to_speech("hello", "en-US", premium_access=False)


# ---------- line_translator_bot handler integration ----------


@pytest.fixture
def json_settings_path(tmp_path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setenv("USER_SETTINGS_JSON_PATH", str(path))
    return path


@pytest.fixture
def subscriptions_json_path(tmp_path, monkeypatch):
    path = tmp_path / "subscriptions.json"
    monkeypatch.setenv("SUBSCRIPTIONS_JSON_PATH", str(path))
    return path


@contextmanager
def _mock_firestore_unavailable():
    exc = Exception("Firestore unavailable")
    with patch("line_translator_bot._get_db", side_effect=exc), patch(
        "firestore_client._get_db", side_effect=exc
    ):
        yield


def test_handle_message_blocks_ai_translation_without_premium(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_user_setting

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )

        event = MagicMock()
        event.message.text = "你好"
        event.source.user_id = "U123"
        event.source.group_id = None
        event.reply_token = "reply-token"

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate"
        ) as mock_translate:
            handle_message(event)

    mock_translate.assert_not_called()
    mock_reply.assert_called_once()
    reply_text = mock_reply.call_args[0][1]
    assert "paid" in reply_text.lower() or "premium" in reply_text.lower() or "付費" in reply_text


def test_handle_message_allows_pair_translation_without_premium(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_user_setting

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "pair",
                "source_lang": "en",
                "target_lang": "zh-TW",
            },
        )

        event = MagicMock()
        event.message.text = "hello"
        event.source.user_id = "U123"
        event.source.group_id = None
        event.reply_token = "reply-token"

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate",
            return_value="你好",
        ) as mock_translate, patch(
            "line_translator_bot.get_user_display_name",
            return_value="Tester",
        ):
            handle_message(event)

    mock_translate.assert_called_once()
    mock_reply.assert_called_once()


def test_handle_audio_message_blocks_voice_without_premium(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_audio_message, save_user_setting

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "pair",
                "source_lang": "en",
                "target_lang": "zh-TW",
            },
        )

        event = MagicMock()
        event.message.id = "audio-msg-id"
        event.source.user_id = "U123"
        event.source.group_id = None
        event.reply_token = "reply-token"

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.download_line_audio"
        ) as mock_download, patch(
            "line_translator_bot.speech_to_text"
        ) as mock_stt:
            handle_audio_message(event)

    mock_download.assert_not_called()
    mock_stt.assert_not_called()
    mock_reply.assert_called_once()


def test_handle_audio_message_allows_voice_with_premium(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_audio_message, save_user_setting, save_user_subscription

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "pair",
                "source_lang": "en",
                "target_lang": "zh-TW",
            },
        )
        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        event = MagicMock()
        event.message.id = "audio-msg-id"
        event.source.user_id = "U123"
        event.source.group_id = None
        event.reply_token = "reply-token"

        with patch("line_translator_bot.send_reply"), patch(
            "line_translator_bot.download_line_audio",
            return_value=b"audio-bytes",
        ) as mock_download, patch(
            "line_translator_bot.speech_to_text",
            return_value="hello",
        ) as mock_stt, patch(
            "line_translator_bot.detect_and_translate",
            return_value="你好",
        ), patch(
            "line_translator_bot.get_user_display_name",
            return_value="Tester",
        ):
            handle_audio_message(event)

    mock_download.assert_called_once()
    mock_stt.assert_called_once()
    assert mock_stt.call_args.kwargs.get("premium_access") is True
