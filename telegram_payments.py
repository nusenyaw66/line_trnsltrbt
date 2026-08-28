"""Telegram Stars invoice links and subscription persistence for spoken voice."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from firestore_client import get_user_subscription, save_user_subscription
from subscription_models import personal_subscription_from_settings

VOICE_PLAN_TYPE = "voice"
PAYLOAD_PREFIX = "voice:"
SUBSCRIPTION_PERIOD_SECONDS = 2592000
DEFAULT_STARS_AMOUNT = 250
MAX_STARS_AMOUNT = 10000
STACKED_SUB_DAYS = 40


def stars_amount() -> int:
    raw = os.getenv("TELEGRAM_VOICE_SUB_STARS", str(DEFAULT_STARS_AMOUNT)).strip()
    try:
        amount = int(raw)
    except ValueError as exc:
        raise ValueError(f"TELEGRAM_VOICE_SUB_STARS must be an integer, got {raw!r}") from exc
    if amount < 0 or amount > MAX_STARS_AMOUNT:
        raise ValueError(
            f"TELEGRAM_VOICE_SUB_STARS must be between 0 and {MAX_STARS_AMOUNT}, got {amount}"
        )
    return amount


def is_free_beta() -> bool:
    """True when Stars price is 0 (Telegram does not accept 0-Star invoices)."""
    return stars_amount() == 0


def grant_free_voice_subscription(user_id: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    """Activate a no-expiry voice plan for beta (0 Stars)."""
    now = at or datetime.now(timezone.utc)
    existing = get_user_subscription(user_id)
    updates: Dict[str, Any] = {
        "subscribed": True,
        "plan_type": VOICE_PLAN_TYPE,
        "subscription_expires_at": None,
    }
    if not existing.get("subscription_activated_at"):
        updates["subscription_activated_at"] = now.isoformat()
    save_user_subscription(user_id, updates)
    return updates


def build_invoice_payload(user_id: str) -> str:
    return f"{PAYLOAD_PREFIX}{user_id}"


def parse_invoice_payload(payload: Optional[str]) -> Optional[str]:
    if not payload or not isinstance(payload, str):
        return None
    if not payload.startswith(PAYLOAD_PREFIX):
        return None
    user_id = payload[len(PAYLOAD_PREFIX) :].strip()
    return user_id or None


def should_accept_pre_checkout(
    user_id: str,
    payload: Optional[str],
    user_subscription: Dict[str, Any],
    at: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """Accept unless the payload is invalid or the user already has a long-lived sub."""
    parsed = parse_invoice_payload(payload)
    if parsed is None or parsed != str(user_id):
        return False, "Invalid payment."
    now = at or datetime.now(timezone.utc)
    personal = personal_subscription_from_settings(str(user_id), user_subscription)
    if personal.is_active(at=now) and personal.expires_at is not None:
        expires_at = personal.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > now + timedelta(days=STACKED_SUB_DAYS):
            return False, "You already have an active subscription."
    return True, ""


def subscription_updates_from_payment(
    payment: Dict[str, Any],
    user_id: str,
    at: Optional[datetime] = None,
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build Firestore updates from Telegram successful_payment."""
    now = at or datetime.now(timezone.utc)
    unix_expiry = payment.get("subscription_expiration_date")
    if unix_expiry:
        expires_at = datetime.fromtimestamp(int(unix_expiry), tz=timezone.utc)
    else:
        expires_at = now + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS)
    current = existing if existing is not None else get_user_subscription(user_id)
    activated_at = current.get("subscription_activated_at")
    updates: Dict[str, Any] = {
        "subscribed": True,
        "plan_type": VOICE_PLAN_TYPE,
        "subscription_expires_at": expires_at.isoformat(),
        "telegram_payment_charge_id": payment.get("telegram_payment_charge_id"),
    }
    if not activated_at:
        updates["subscription_activated_at"] = now.isoformat()
    return updates


def _telegram_api(bot_token: str, method: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"Telegram {method} HTTP {exc.code}: {detail}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description', 'unknown')}")
    return body


def create_invoice_link(
    bot_token: str,
    user_id: str,
    title: str = "Spoken voice translation",
    description: str = "30-day subscription: translated voice notes spoken back to you.",
) -> str:
    amount = stars_amount()
    if amount < 1:
        raise RuntimeError("createInvoiceLink requires at least 1 Star; use free-beta grant instead")
    body = _telegram_api(
        bot_token,
        "createInvoiceLink",
        {
            "title": title,
            "description": description,
            "payload": build_invoice_payload(user_id),
            "currency": "XTR",
            "prices": [{"label": "Monthly spoken translation", "amount": amount}],
            "subscription_period": SUBSCRIPTION_PERIOD_SECONDS,
        },
    )
    result = body.get("result")
    if not result or not isinstance(result, str):
        raise RuntimeError("createInvoiceLink returned no link")
    return result


def answer_pre_checkout_query(
    bot_token: str,
    pre_checkout_query_id: str,
    ok: bool,
    error_message: str = "",
) -> None:
    payload: Dict[str, Any] = {
        "pre_checkout_query_id": pre_checkout_query_id,
        "ok": ok,
    }
    if not ok and error_message:
        payload["error_message"] = error_message
    _telegram_api(bot_token, "answerPreCheckoutQuery", payload, timeout=8)


def handle_pre_checkout_query(query: Dict[str, Any], bot_token: str) -> None:
    query_id = query.get("id")
    if not query_id:
        return
    user_id = str((query.get("from") or {}).get("id", ""))
    payload = query.get("invoice_payload") or ""
    try:
        subscription = get_user_subscription(user_id) if user_id else {}
        ok, error_message = should_accept_pre_checkout(user_id, payload, subscription)
        answer_pre_checkout_query(bot_token, str(query_id), ok, error_message)
    except Exception as exc:
        print(f"ERROR answering pre_checkout_query: {exc}")
        try:
            answer_pre_checkout_query(bot_token, str(query_id), False, "Payment could not be confirmed.")
        except Exception as nested:
            print(f"ERROR sending pre_checkout failure: {nested}")


def handle_successful_payment(user_id: str, payment: Dict[str, Any]) -> None:
    payload_user = parse_invoice_payload(payment.get("invoice_payload"))
    if payload_user != str(user_id):
        print(
            f"WARNING: successful_payment payload user {payload_user!r} "
            f"does not match from.id {user_id!r}; ignoring"
        )
        return
    existing = get_user_subscription(user_id)
    updates = subscription_updates_from_payment(payment, user_id, existing=existing)
    save_user_subscription(user_id, updates)
