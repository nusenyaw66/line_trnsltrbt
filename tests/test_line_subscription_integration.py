"""Integration tests with mock LINE events for subscription gating (Task 6)."""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

pytest.importorskip("flask")
pytest.importorskip("linebot")

from linebot.v3.webhooks import GroupSource  # noqa: E402

UTC = timezone.utc
FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)
CHECK_AT = datetime(2021, 6, 1, tzinfo=UTC)


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


def _make_personal_text_event(user_id: str, text: str) -> MagicMock:
    event = MagicMock()
    event.message.text = text
    event.source.user_id = user_id
    event.source.group_id = None
    event.reply_token = "reply-token"
    return event


def _make_group_text_event(user_id: str, group_id: str, text: str) -> MagicMock:
    event = MagicMock()
    event.message.text = text
    event.source = GroupSource(type="group", group_id=group_id, user_id=user_id)
    event.reply_token = "reply-token"
    return event


def _make_personal_audio_event(user_id: str) -> MagicMock:
    event = MagicMock()
    event.message.id = "audio-msg-id"
    event.source.user_id = user_id
    event.source.group_id = None
    event.reply_token = "reply-token"
    return event


def _make_group_audio_event(user_id: str, group_id: str) -> MagicMock:
    event = MagicMock()
    event.message.id = "audio-msg-id"
    event.source = GroupSource(type="group", group_id=group_id, user_id=user_id)
    event.reply_token = "reply-token"
    return event


def _premium_reply_assertion(reply_text: str) -> None:
    lowered = reply_text.lower()
    assert "paid" in lowered or "premium" in lowered or "付費" in reply_text


# ---------- personal chat scenarios ----------


def test_personal_ai_translation_blocked_without_subscription(json_settings_path):
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

        event = _make_personal_text_event("U123", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate"
        ) as mock_translate:
            handle_message(event)

    mock_translate.assert_not_called()
    mock_reply.assert_called_once()
    _premium_reply_assertion(mock_reply.call_args[0][1])


def test_personal_ai_translation_blocked_with_expired_subscription(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_user_setting, save_user_subscription

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )
        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": PAST.isoformat(),
            },
        )

        event = _make_personal_text_event("U123", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate"
        ) as mock_translate, patch("subscription_models.datetime") as mock_dt:
            mock_dt.now.return_value = CHECK_AT
            handle_message(event)

    mock_translate.assert_not_called()
    mock_reply.assert_called_once()
    _premium_reply_assertion(mock_reply.call_args[0][1])


def test_personal_ai_translation_allowed_with_subscription(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_user_setting, save_user_subscription

        save_user_setting(
            "U123",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )
        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        event = _make_personal_text_event("U123", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate",
            return_value="hello",
        ) as mock_translate, patch(
            "line_translator_bot.get_user_display_name",
            return_value="Tester",
        ):
            handle_message(event)

    mock_translate.assert_called_once()
    assert mock_translate.call_args.kwargs.get("premium_access") is True
    mock_reply.assert_called_once()


def test_personal_voice_blocked_without_subscription(json_settings_path):
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

        event = _make_personal_audio_event("U123")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.download_line_audio"
        ) as mock_download, patch(
            "line_translator_bot.speech_to_text"
        ) as mock_stt:
            handle_audio_message(event)

    mock_download.assert_not_called()
    mock_stt.assert_not_called()
    mock_reply.assert_called_once()
    _premium_reply_assertion(mock_reply.call_args[0][1])


def test_personal_voice_allowed_with_subscription(
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

        event = _make_personal_audio_event("U123")

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


# ---------- group chat scenarios ----------


def test_group_ai_translation_blocked_without_group_activation(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_group_setting

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )

        event = _make_group_text_event("U999", "G456", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate"
        ) as mock_translate:
            handle_message(event)

    mock_translate.assert_not_called()
    mock_reply.assert_called_once()
    _premium_reply_assertion(mock_reply.call_args[0][1])


def test_group_ai_translation_allowed_via_personal_subscription(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message, save_group_setting, save_user_subscription

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )
        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        event = _make_group_text_event("U123", "G456", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate",
            return_value="hello",
        ) as mock_translate, patch(
            "line_translator_bot.get_user_display_name",
            return_value="Subscriber",
        ):
            handle_message(event)

    mock_translate.assert_called_once()
    assert mock_translate.call_args.kwargs.get("premium_access") is True
    mock_reply.assert_called_once()


def test_group_ai_translation_allowed_via_group_activation(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import (
            handle_message,
            save_group_activation,
            save_group_setting,
        )

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )
        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        event = _make_group_text_event("U999", "G456", "你好")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.detect_and_translate",
            return_value="hello",
        ) as mock_translate, patch(
            "line_translator_bot.get_user_display_name",
            return_value="Member",
        ):
            handle_message(event)

    mock_translate.assert_called_once()
    assert mock_translate.call_args.kwargs.get("premium_access") is True
    mock_reply.assert_called_once()


def test_group_voice_blocked_without_group_activation(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_audio_message, save_group_setting

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "pair",
                "source_lang": "en",
                "target_lang": "zh-TW",
            },
        )

        event = _make_group_audio_event("U999", "G456")

        with patch("line_translator_bot.send_reply") as mock_reply, patch(
            "line_translator_bot.download_line_audio"
        ) as mock_download, patch(
            "line_translator_bot.speech_to_text"
        ) as mock_stt:
            handle_audio_message(event)

    mock_download.assert_not_called()
    mock_stt.assert_not_called()
    mock_reply.assert_called_once()
    _premium_reply_assertion(mock_reply.call_args[0][1])


def test_group_voice_allowed_via_group_activation(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import (
            handle_audio_message,
            save_group_activation,
            save_group_setting,
        )

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "pair",
                "source_lang": "en",
                "target_lang": "zh-TW",
            },
        )
        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        event = _make_group_audio_event("U999", "G456")

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
            return_value="Member",
        ):
            handle_audio_message(event)

    mock_download.assert_called_once()
    mock_stt.assert_called_once()
    assert mock_stt.call_args.kwargs.get("premium_access") is True


def test_group_member_without_personal_sub_uses_group_premium_only(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import (
            handle_message,
            has_premium_access,
            save_group_activation,
            save_group_setting,
        )

        save_group_setting(
            "G456",
            {
                "enabled": True,
                "mode": "american",
                "target_lang": "en-US",
            },
        )
        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        assert has_premium_access("U999", group_id="G456") is True
        assert has_premium_access("U999") is False

        event = _make_group_text_event("U999", "G456", "你好")

        with patch("line_translator_bot.send_reply"), patch(
            "line_translator_bot.detect_and_translate",
            return_value="hello",
        ) as mock_translate, patch(
            "line_translator_bot.get_user_display_name",
            return_value="Member",
        ):
            handle_message(event)

    assert mock_translate.call_args.kwargs.get("premium_access") is True
