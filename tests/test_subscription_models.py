"""Tests for subscription data models and settings helpers (Task 1)."""

import json
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

from subscription_models import (  # noqa: E402
    GroupSubscription,
    PersonalSubscription,
    group_subscription_from_settings,
    group_subscription_to_settings,
    personal_subscription_from_settings,
    personal_subscription_to_settings,
)

UTC = timezone.utc
FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


# ---------- PersonalSubscription.is_active ----------


def test_personal_subscription_active():
    sub = PersonalSubscription(
        user_id="U123",
        subscribed=True,
        expires_at=FUTURE,
    )
    assert sub.is_active(at=FUTURE - timedelta(days=1)) is True


def test_personal_subscription_inactive_when_not_subscribed():
    sub = PersonalSubscription(user_id="U123", subscribed=False, expires_at=FUTURE)
    assert sub.is_active(at=FUTURE - timedelta(days=1)) is False


def test_personal_subscription_inactive_when_expired():
    sub = PersonalSubscription(user_id="U123", subscribed=True, expires_at=PAST)
    assert sub.is_active(at=datetime(2021, 1, 1, tzinfo=UTC)) is False


def test_personal_subscription_active_without_expiry():
    sub = PersonalSubscription(user_id="U123", subscribed=True, expires_at=None)
    assert sub.is_active() is True


# ---------- GroupSubscription.is_active ----------


def test_group_subscription_active():
    sub = GroupSubscription(
        group_id="G456",
        activated_by_user_id="U123",
        activated_at=PAST,
        expires_at=FUTURE,
    )
    assert sub.is_active(at=FUTURE - timedelta(days=1)) is True


def test_group_subscription_inactive_without_activator():
    sub = GroupSubscription(group_id="G456", activated_by_user_id=None, expires_at=FUTURE)
    assert sub.is_active(at=FUTURE - timedelta(days=1)) is False


def test_group_subscription_inactive_when_expired():
    sub = GroupSubscription(
        group_id="G456",
        activated_by_user_id="U123",
        expires_at=PAST,
    )
    assert sub.is_active(at=datetime(2021, 1, 1, tzinfo=UTC)) is False


# ---------- settings dict round-trip ----------


def test_personal_subscription_settings_round_trip():
    sub = PersonalSubscription(
        user_id="U123",
        subscribed=True,
        expires_at=FUTURE,
        plan_type="premium",
        activated_at=PAST,
    )
    settings = personal_subscription_to_settings(sub)
    restored = personal_subscription_from_settings("U123", settings)
    assert restored == sub


def test_group_subscription_settings_round_trip():
    sub = GroupSubscription(
        group_id="G456",
        activated_by_user_id="U123",
        activated_at=PAST,
        expires_at=FUTURE,
    )
    settings = group_subscription_to_settings(sub)
    restored = group_subscription_from_settings("G456", settings)
    assert restored == sub


def test_personal_subscription_from_settings_uses_defaults():
    sub = personal_subscription_from_settings("U999", {})
    assert sub == PersonalSubscription(user_id="U999")


# ---------- line_translator_bot settings integration ----------


@pytest.fixture
def json_settings_path(tmp_path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setenv("USER_SETTINGS_JSON_PATH", str(path))
    return path


@contextmanager
def _mock_firestore_unavailable():
    exc = Exception("Firestore unavailable")
    with patch("line_translator_bot._get_db", side_effect=exc), patch(
        "firestore_client._get_db", side_effect=exc
    ):
        yield


def test_get_user_setting_includes_subscription_defaults(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import get_user_setting

        settings = get_user_setting("U123")

    assert settings["subscribed"] is False
    assert settings["subscription_expires_at"] is None
    assert settings["plan_type"] is None
    assert settings["subscription_activated_at"] is None


def test_get_group_setting_includes_subscription_defaults(json_settings_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import get_group_setting

        settings = get_group_setting("G456")

    assert settings["subscription_activated_by_user_id"] is None
    assert settings["subscription_activated_at"] is None
    assert settings["subscription_expires_at"] is None


@pytest.fixture
def subscriptions_json_path(tmp_path, monkeypatch):
    path = tmp_path / "subscriptions.json"
    monkeypatch.setenv("SUBSCRIPTIONS_JSON_PATH", str(path))
    return path


def test_save_user_subscription_persists_to_json(subscriptions_json_path):
    with _mock_firestore_unavailable():
        from firestore_client import get_user_subscription, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
                "plan_type": "premium",
                "subscription_activated_at": PAST.isoformat(),
            },
        )
        settings = get_user_subscription("U123")

    assert settings["subscribed"] is True
    assert settings["plan_type"] == "premium"
    assert settings["subscription_expires_at"] == FUTURE.isoformat()

    stored = json.loads(subscriptions_json_path.read_text(encoding="utf-8"))
    assert stored["users"]["U123"]["subscribed"] is True
    assert stored["users"]["U123"]["plan_type"] == "premium"


def test_save_group_activation_persists_to_json(subscriptions_json_path):
    with _mock_firestore_unavailable():
        from firestore_client import get_group_activation, save_group_activation

        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_activated_at": PAST.isoformat(),
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )
        settings = get_group_activation("G456")

    assert settings["subscription_activated_by_user_id"] == "U123"
    assert settings["subscription_expires_at"] == FUTURE.isoformat()

    stored = json.loads(subscriptions_json_path.read_text(encoding="utf-8"))
    assert stored["groups"]["G456"]["subscription_activated_by_user_id"] == "U123"


def test_has_premium_access_uses_subscription_store(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import has_premium_access, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        assert has_premium_access("U123") is True
        assert has_premium_access("U999") is False


def test_get_user_subscription_reads_legacy_user_settings_fallback(json_settings_path):
    json_settings_path.write_text(
        json.dumps(
            {
                "U789": {
                    "subscribed": True,
                    "subscription_expires_at": FUTURE.isoformat(),
                    "plan_type": "basic",
                }
            }
        ),
        encoding="utf-8",
    )

    with _mock_firestore_unavailable():
        from line_translator_bot import get_user_subscription

        settings = get_user_subscription("U789")

    assert settings["subscribed"] is True
    assert settings["plan_type"] == "basic"
