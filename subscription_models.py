"""Subscription data models and settings serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@dataclass(frozen=True)
class PersonalSubscription:
    user_id: str
    subscribed: bool = False
    expires_at: Optional[datetime] = None
    plan_type: Optional[str] = None
    activated_at: Optional[datetime] = None

    def is_active(self, at: Optional[datetime] = None) -> bool:
        if not self.subscribed:
            return False
        if self.expires_at is None:
            return True
        now = at or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > now


@dataclass(frozen=True)
class GroupSubscription:
    group_id: str
    activated_by_user_id: Optional[str] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def is_active(self, at: Optional[datetime] = None) -> bool:
        if not self.activated_by_user_id:
            return False
        if self.expires_at is None:
            return True
        now = at or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > now


def personal_subscription_to_settings(sub: PersonalSubscription) -> Dict[str, Any]:
    return {
        "subscribed": sub.subscribed,
        "subscription_expires_at": _format_datetime(sub.expires_at),
        "plan_type": sub.plan_type,
        "subscription_activated_at": _format_datetime(sub.activated_at),
    }


def personal_subscription_from_settings(
    user_id: str,
    settings: Dict[str, Any],
) -> PersonalSubscription:
    return PersonalSubscription(
        user_id=user_id,
        subscribed=bool(settings.get("subscribed", False)),
        expires_at=_parse_datetime(settings.get("subscription_expires_at")),
        plan_type=settings.get("plan_type"),
        activated_at=_parse_datetime(settings.get("subscription_activated_at")),
    )


def group_subscription_to_settings(sub: GroupSubscription) -> Dict[str, Any]:
    return {
        "subscription_activated_by_user_id": sub.activated_by_user_id,
        "subscription_activated_at": _format_datetime(sub.activated_at),
        "subscription_expires_at": _format_datetime(sub.expires_at),
    }


def group_subscription_from_settings(
    group_id: str,
    settings: Dict[str, Any],
) -> GroupSubscription:
    return GroupSubscription(
        group_id=group_id,
        activated_by_user_id=settings.get("subscription_activated_by_user_id"),
        activated_at=_parse_datetime(settings.get("subscription_activated_at")),
        expires_at=_parse_datetime(settings.get("subscription_expires_at")),
    )
