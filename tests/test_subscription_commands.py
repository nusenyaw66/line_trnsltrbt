"""Tests for subscription management commands (Task 4)."""

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

from i18n import format_subscription_expiry, get_localized_subscription_status_lines, get_text  # noqa: E402
from subscription_commands import (  # noqa: E402
    build_activate_group_updates,
    build_subscribe_message_key,
)

UTC = timezone.utc
FUTURE = datetime(2027, 6, 15, 12, 0, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


# ---------- parse_switch_command ----------


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("/subscribe", {"type": "subscribe"}),
        ("/activate group", {"type": "activate_group"}),
        ("/status subscription", {"type": "status_subscription"}),
    ],
)
def test_parse_subscription_commands(msg, expected):
    from line_translator_bot import parse_switch_command

    assert parse_switch_command(msg) == expected


def test_activate_without_group_is_not_a_command():
    from line_translator_bot import parse_switch_command

    assert parse_switch_command("/activate") is None


def test_status_without_subscription_subcommand_still_status():
    from line_translator_bot import parse_switch_command

    assert parse_switch_command("/status") == {"type": "status"}


# ---------- subscribe message selection ----------


def test_build_subscribe_message_key_active():
    settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
        "plan_type": "premium",
    }
    key, kwargs = build_subscribe_message_key("U123", settings)
    assert key == "subscription_active_info"
    assert kwargs["plan"] == "premium"
    assert "expires" in kwargs


def test_build_subscribe_message_key_inactive():
    key, kwargs = build_subscribe_message_key("U123", {})
    assert key == "subscription_how_to_subscribe"
    assert "url" in kwargs


def test_build_subscribe_message_key_expired():
    settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
        "plan_type": "premium",
    }
    key, kwargs = build_subscribe_message_key("U123", settings, at=datetime(2021, 1, 1, tzinfo=UTC))
    assert key == "subscription_expired_info"
    assert "expires" in kwargs


# ---------- activate group ----------


def test_build_activate_group_updates_copies_personal_expiry():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
        "plan_type": "premium",
    }
    activated_at = FUTURE - timedelta(days=1)
    result = build_activate_group_updates("U123", user_settings, "G456", at=activated_at)
    assert result.ok is True
    assert result.group_updates == {
        "subscription_activated_by_user_id": "U123",
        "subscription_activated_at": activated_at.isoformat(),
        "subscription_expires_at": FUTURE.isoformat(),
    }


def test_build_activate_group_updates_requires_active_personal():
    result = build_activate_group_updates("U123", {}, "G456")
    assert result.ok is False
    assert result.message_key == "subscription_activate_group_requires_personal"


def test_build_activate_group_updates_requires_group_id():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    result = build_activate_group_updates("U123", user_settings, group_id=None)
    assert result.ok is False
    assert result.message_key == "subscription_activate_group_requires_group"


# ---------- subscription status lines ----------


def test_get_localized_subscription_status_lines_personal_active():
    lines = get_localized_subscription_status_lines(
        user_settings={
            "subscribed": True,
            "subscription_expires_at": FUTURE.isoformat(),
            "plan_type": "premium",
        },
        lang="en",
    )
    text = "\n".join(lines)
    assert "Personal" in text or "personal" in text.lower()
    assert "premium" in text
    assert "Active" in text or "active" in text.lower()


def test_get_localized_subscription_status_lines_includes_group():
    lines = get_localized_subscription_status_lines(
        user_settings={"subscribed": False},
        group_settings={
            "subscription_activated_by_user_id": "U123",
            "subscription_expires_at": FUTURE.isoformat(),
        },
        lang="en",
        is_group=True,
    )
    text = "\n".join(lines)
    assert "Group" in text or "group" in text.lower()
    assert "U123" in text


def test_format_subscription_expiry_none():
    assert format_subscription_expiry(None, lang="en") == get_text("subscription_no_expiry", "en")


# ---------- handler integration ----------


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


def test_handle_subscribe_command_shows_how_to_subscribe(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_subscribe_command

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_subscribe_command("U123", "reply-token")

    mock_reply.assert_called_once()
    reply_text = mock_reply.call_args[0][1]
    assert "subscribe" in reply_text.lower() or "訂閱" in reply_text or "サブスク" in reply_text


def test_handle_subscribe_command_shows_active_status(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_subscribe_command, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
                "plan_type": "premium",
            },
        )

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_subscribe_command("U123", "reply-token")

    reply_text = mock_reply.call_args[0][1]
    assert "premium" in reply_text.lower() or "Premium" in reply_text


def test_handle_activate_group_command_persists_group_subscription(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import (
            get_group_subscription,
            handle_activate_group_command,
            save_user_subscription,
        )

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
                "plan_type": "premium",
            },
        )

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_activate_group_command("U123", "reply-token", group_id="G456")

        mock_reply.assert_called_once()
        group_subscription = get_group_subscription("G456")
        assert group_subscription["subscription_activated_by_user_id"] == "U123"
        assert group_subscription["subscription_expires_at"] == FUTURE.isoformat()


def test_handle_activate_group_command_rejects_without_personal(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_activate_group_command

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_activate_group_command("U123", "reply-token", group_id="G456")

    reply_text = mock_reply.call_args[0][1]
    assert "personal" in reply_text.lower() or "個人" in reply_text or "個人" in reply_text


def test_handle_activate_group_command_rejects_outside_group(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_activate_group_command, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_activate_group_command("U123", "reply-token", group_id=None)

    reply_text = mock_reply.call_args[0][1]
    assert "group" in reply_text.lower() or "群組" in reply_text or "グループ" in reply_text


def test_handle_status_subscription_command(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_status_subscription_command, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
                "plan_type": "premium",
            },
        )

        with patch("line_translator_bot.send_reply") as mock_reply:
            handle_status_subscription_command("U123", "reply-token")

    reply_text = mock_reply.call_args[0][1]
    assert "premium" in reply_text.lower() or "Premium" in reply_text


def test_handle_message_routes_subscribe_command(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import handle_message

        event = MagicMock()
        event.message.text = "/subscribe"
        event.source.user_id = "U123"
        event.source.group_id = None
        event.reply_token = "reply-token"

        with patch("line_translator_bot.handle_subscribe_command") as mock_handler:
            handle_message(event)

    mock_handler.assert_called_once_with("U123", "reply-token", None)
