"""Tests for Telegram Stars invoice payload, pre-checkout, and subscription writes."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram_payments import (
    VOICE_PLAN_TYPE,
    build_invoice_payload,
    handle_pre_checkout_query,
    handle_successful_payment,
    parse_invoice_payload,
    should_accept_pre_checkout,
    stars_amount,
    subscription_updates_from_payment,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def test_stars_amount_allows_zero(monkeypatch):
    monkeypatch.setenv("TELEGRAM_VOICE_SUB_STARS", "0")
    assert stars_amount() == 0
    from telegram_payments import is_free_beta

    assert is_free_beta() is True


def test_stars_amount_rejects_negative(monkeypatch):
    monkeypatch.setenv("TELEGRAM_VOICE_SUB_STARS", "-1")
    with pytest.raises(ValueError):
        stars_amount()


def test_grant_free_voice_subscription():
    from telegram_payments import grant_free_voice_subscription

    with patch("telegram_payments.get_user_subscription", return_value={}), patch(
        "telegram_payments.save_user_subscription"
    ) as save:
        updates = grant_free_voice_subscription("42", at=NOW)
    save.assert_called_once()
    assert updates["subscribed"] is True
    assert updates["plan_type"] == VOICE_PLAN_TYPE
    assert updates["subscription_expires_at"] is None
    assert "subscription_activated_at" in updates


def test_payload_round_trip():
    payload = build_invoice_payload("42")
    assert parse_invoice_payload(payload) == "42"
    assert parse_invoice_payload("nope") is None
    assert parse_invoice_payload("voice:") is None


def test_pre_checkout_rejects_invalid_payload():
    ok, err = should_accept_pre_checkout("42", "bad", {}, at=NOW)
    assert ok is False
    assert "Invalid" in err


def test_pre_checkout_rejects_mismatched_user():
    ok, _ = should_accept_pre_checkout("42", build_invoice_payload("99"), {}, at=NOW)
    assert ok is False


def test_pre_checkout_accepts_new_user():
    ok, err = should_accept_pre_checkout("42", build_invoice_payload("42"), {}, at=NOW)
    assert ok is True
    assert err == ""


def test_pre_checkout_rejects_stacked_subscription():
    far = (NOW + timedelta(days=50)).isoformat()
    ok, err = should_accept_pre_checkout(
        "42",
        build_invoice_payload("42"),
        {"subscribed": True, "subscription_expires_at": far},
        at=NOW,
    )
    assert ok is False
    assert "already" in err.lower()


def test_subscription_updates_prefer_telegram_expiry():
    unix = int((NOW + timedelta(days=30)).timestamp())
    updates = subscription_updates_from_payment(
        {
            "subscription_expiration_date": unix,
            "telegram_payment_charge_id": "chg_1",
        },
        "42",
        at=NOW,
        existing={"subscribed": False},
    )
    assert updates["subscribed"] is True
    assert updates["plan_type"] == VOICE_PLAN_TYPE
    assert updates["telegram_payment_charge_id"] == "chg_1"
    assert updates["subscription_expires_at"] == datetime.fromtimestamp(unix, tz=UTC).isoformat()
    assert "subscription_activated_at" in updates


def test_subscription_updates_keep_existing_activated_at():
    updates = subscription_updates_from_payment(
        {"subscription_expiration_date": int((NOW + timedelta(days=30)).timestamp())},
        "42",
        at=NOW,
        existing={"subscription_activated_at": "2026-01-01T00:00:00+00:00"},
    )
    assert "subscription_activated_at" not in updates


def test_handle_pre_checkout_answers_telegram():
    query = {
        "id": "q1",
        "from": {"id": 42},
        "invoice_payload": build_invoice_payload("42"),
    }
    with patch("telegram_payments.get_user_subscription", return_value={}), patch(
        "telegram_payments.answer_pre_checkout_query"
    ) as answer:
        handle_pre_checkout_query(query, "token")
    answer.assert_called_once_with("token", "q1", True, "")


def test_handle_successful_payment_persists():
    payment = {
        "invoice_payload": build_invoice_payload("42"),
        "telegram_payment_charge_id": "chg",
        "subscription_expiration_date": int((NOW + timedelta(days=30)).timestamp()),
    }
    with patch("telegram_payments.get_user_subscription", return_value={}), patch(
        "telegram_payments.save_user_subscription"
    ) as save:
        handle_successful_payment("42", payment)
    save.assert_called_once()
    user_id, updates = save.call_args[0]
    assert user_id == "42"
    assert updates["plan_type"] == "voice"
    assert updates["telegram_payment_charge_id"] == "chg"


def test_handle_successful_payment_ignores_payload_mismatch():
    payment = {"invoice_payload": build_invoice_payload("99")}
    with patch("telegram_payments.save_user_subscription") as save:
        handle_successful_payment("42", payment)
    save.assert_not_called()
