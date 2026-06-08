"""Premium feature classification helpers (Task 3)."""

from __future__ import annotations

AI_TRANSLATION_MODES = frozenset({"american", "mandarin", "japanese"})


def is_ai_translation_mode(mode: str) -> bool:
    return mode in AI_TRANSLATION_MODES


def requires_premium_for_translation(mode: str, enabled: bool) -> bool:
    return bool(enabled) and is_ai_translation_mode(mode)


def requires_premium_for_voice() -> bool:
    return True
