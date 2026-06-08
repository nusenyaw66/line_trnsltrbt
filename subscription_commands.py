"""Subscription management command helpers (Task 4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from i18n import format_subscription_expiry, get_text
from subscription_models import personal_subscription_from_settings

DEFAULT_SUBSCRIBE_URL = "https://www.tssrct.us"


def subscribe_url() -> str:
    return os.getenv("SUBSCRIBE_URL", DEFAULT_SUBSCRIBE_URL).strip() or DEFAULT_SUBSCRIBE_URL


def build_subscribe_message_key(
    user_id: str,
    user_settings: Dict[str, Any],
    at: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (i18n key, format kwargs) for the /subscribe reply."""
    personal = personal_subscription_from_settings(user_id, user_settings)
    url = subscribe_url()

    if personal.is_active(at=at):
        return (
            "subscription_active_info",
            {
                "plan": personal.plan_type or get_text("subscription_plan_unknown"),
                "expires": format_subscription_expiry(personal.expires_at),
            },
        )

    if personal.subscribed and not personal.is_active(at=at):
        return (
            "subscription_expired_info",
            {
                "expires": format_subscription_expiry(personal.expires_at),
                "url": url,
            },
        )

    return ("subscription_how_to_subscribe", {"url": url})


@dataclass(frozen=True)
class ActivateGroupResult:
    ok: bool
    message_key: str
    message_kwargs: Dict[str, Any]
    group_updates: Optional[Dict[str, Any]] = None


def build_activate_group_updates(
    user_id: str,
    user_settings: Dict[str, Any],
    group_id: Optional[str],
    at: Optional[datetime] = None,
) -> ActivateGroupResult:
    """Validate and build group subscription updates from a personal subscription."""
    if not group_id:
        return ActivateGroupResult(
            ok=False,
            message_key="subscription_activate_group_requires_group",
            message_kwargs={},
        )

    personal = personal_subscription_from_settings(user_id, user_settings)
    if not personal.is_active(at=at):
        return ActivateGroupResult(
            ok=False,
            message_key="subscription_activate_group_requires_personal",
            message_kwargs={},
        )

    now = at or datetime.now(timezone.utc)
    group_updates = {
        "subscription_activated_by_user_id": user_id,
        "subscription_activated_at": now.isoformat(),
        "subscription_expires_at": (
            personal.expires_at.isoformat()
            if personal.expires_at is not None
            else None
        ),
    }
    return ActivateGroupResult(
        ok=True,
        message_key="subscription_group_activated",
        message_kwargs={
            "expires": format_subscription_expiry(personal.expires_at),
        },
        group_updates=group_updates,
    )
