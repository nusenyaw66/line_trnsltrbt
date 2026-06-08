"""Premium subscription access checks (Task 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from subscription_models import (
    group_subscription_from_settings,
    personal_subscription_from_settings,
)


def has_premium_access(
    user_id: str,
    user_settings: Dict[str, Any],
    group_id: Optional[str] = None,
    group_settings: Optional[Dict[str, Any]] = None,
    at: Optional[datetime] = None,
) -> bool:
    """Return True when the user has active personal or group premium access."""
    personal = personal_subscription_from_settings(user_id, user_settings)
    if personal.is_active(at=at):
        return True

    if group_id and group_settings is not None:
        group = group_subscription_from_settings(group_id, group_settings)
        if group.is_active(at=at):
            return True

    return False
