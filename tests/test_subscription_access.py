"""Unit tests for has_premium_access edge cases (Task 6)."""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

pytest.importorskip("flask")
pytest.importorskip("linebot")

from subscription_access import has_premium_access  # noqa: E402

UTC = timezone.utc
FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)
CHECK_AT = datetime(2021, 6, 1, tzinfo=UTC)


# ---------- no subscription ----------


def test_has_premium_access_false_with_empty_user_settings():
    assert has_premium_access("U123", {}) is False


def test_has_premium_access_false_when_subscribed_flag_false():
    settings = {"subscribed": False, "subscription_expires_at": FUTURE.isoformat()}
    assert has_premium_access("U123", settings) is False


def test_has_premium_access_false_with_group_id_but_no_group_settings():
    user_settings = {"subscribed": False}
    assert has_premium_access("U123", user_settings, group_id="G456", group_settings=None) is False


def test_has_premium_access_false_with_empty_group_settings():
    user_settings = {"subscribed": False}
    assert has_premium_access("U123", user_settings, group_id="G456", group_settings={}) is False


def test_has_premium_access_ignores_group_when_group_id_omitted():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert has_premium_access("U999", user_settings, group_settings=group_settings) is False


def test_has_premium_access_false_with_unactivated_group():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": None,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert (
        has_premium_access(
            "U999",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
        )
        is False
    )


# ---------- expired subscription ----------


def test_has_premium_access_false_for_expired_personal_subscription():
    settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
    }
    assert has_premium_access("U123", settings, at=CHECK_AT) is False


def test_has_premium_access_false_for_expired_group_subscription():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": PAST.isoformat(),
    }
    assert (
        has_premium_access(
            "U999",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is False
    )


def test_has_premium_access_false_when_personal_and_group_both_expired():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
    }
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": PAST.isoformat(),
    }
    assert (
        has_premium_access(
            "U123",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is False
    )


# ---------- personal vs group precedence ----------


def test_has_premium_access_true_for_active_personal_subscription():
    settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert has_premium_access("U123", settings, at=CHECK_AT) is True


def test_has_premium_access_true_for_active_group_subscription_non_subscriber():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert (
        has_premium_access(
            "U999",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is True
    )


def test_has_premium_access_personal_wins_when_both_active():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert (
        has_premium_access(
            "U123",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is True
    )


def test_has_premium_access_group_grants_access_when_personal_expired():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
    }
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": FUTURE.isoformat(),
    }
    assert (
        has_premium_access(
            "U999",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is True
    )


def test_has_premium_access_personal_grants_access_when_group_expired():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": FUTURE.isoformat(),
    }
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": PAST.isoformat(),
    }
    assert (
        has_premium_access(
            "U123",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is True
    )


def test_has_premium_access_false_when_only_personal_expired_in_group_context():
    user_settings = {
        "subscribed": True,
        "subscription_expires_at": PAST.isoformat(),
    }
    group_settings = {
        "subscription_activated_by_user_id": None,
        "subscription_expires_at": None,
    }
    assert (
        has_premium_access(
            "U123",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is False
    )


# ---------- subscriptions without explicit expiry ----------


def test_has_premium_access_true_for_personal_without_expiry():
    settings = {"subscribed": True, "subscription_expires_at": None}
    assert has_premium_access("U123", settings, at=CHECK_AT) is True


def test_has_premium_access_true_for_group_without_expiry():
    user_settings = {"subscribed": False}
    group_settings = {
        "subscription_activated_by_user_id": "U123",
        "subscription_expires_at": None,
    }
    assert (
        has_premium_access(
            "U999",
            user_settings,
            group_id="G456",
            group_settings=group_settings,
            at=CHECK_AT,
        )
        is True
    )


# ---------- line_translator_bot store integration ----------


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


def test_bot_has_premium_access_personal_from_store(json_settings_path, subscriptions_json_path):
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


def test_bot_has_premium_access_group_from_store(json_settings_path, subscriptions_json_path):
    with _mock_firestore_unavailable():
        from line_translator_bot import has_premium_access, save_group_activation

        save_group_activation(
            "G456",
            {
                "subscription_activated_by_user_id": "U123",
                "subscription_expires_at": FUTURE.isoformat(),
            },
        )

        assert has_premium_access("U999", group_id="G456") is True
        assert has_premium_access("U999", group_id="G789") is False


def test_bot_has_premium_access_expired_personal_from_store(
    json_settings_path, subscriptions_json_path
):
    with _mock_firestore_unavailable():
        from line_translator_bot import has_premium_access, save_user_subscription

        save_user_subscription(
            "U123",
            {
                "subscribed": True,
                "subscription_expires_at": PAST.isoformat(),
            },
        )

        with patch("subscription_models.datetime") as mock_dt:
            mock_dt.now.return_value = CHECK_AT
            assert has_premium_access("U123") is False
