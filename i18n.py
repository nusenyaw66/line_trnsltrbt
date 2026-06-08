"""Localization (i18n) for translator-bot slash command UX.

- English strings live in ``locales/en.json`` (sole static catalog).
- ``/help`` and ``/status`` are composed in English then translated at runtime via
  ``ui_translate`` when ``ui_lang`` is not ``en``.
- Other command replies use English from ``en.json`` regardless of ``ui_lang``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple, Union

from subscription_models import (
    group_subscription_from_settings,
    personal_subscription_from_settings,
)
from ui_translate import translate_ui_lines

LOCALES_DIR = Path(__file__).parent / "locales"

DEFAULT_LANG = "en"

# Offline / test fallback when Google client is unavailable.
_FALLBACK_UI_LANGS: frozenset[str] = frozenset({
    "en", "zh-TW", "ja", "ko", "es", "th", "id", "fil", "vi", "fr", "de", "it",
})
_FALLBACK_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "zh-TW": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "th": "Thai",
    "id": "Indonesian",
    "fil": "Filipino",
    "vi": "Vietnamese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
}

_GOOGLE_LANG_CACHE: Optional[Tuple[frozenset[str], dict[str, str]]] = None

# User-facing aliases → canonical code. Keys are lower-case (spaces stripped).
_ALIAS_MAP: dict[str, str] = {
    "en": "en",
    "english": "en",
    "eng": "en",

    "zh-tw": "zh-TW",
    "zh_tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh_hant": "zh-TW",
    "zh-hans": "zh-TW",
    "zh_hans": "zh-TW",
    "zh-cn": "zh-TW",
    "zh_cn": "zh-TW",
    "zhtw": "zh-TW",
    "tw": "zh-TW",
    "traditional": "zh-TW",
    "繁中": "zh-TW",
    "繁體中文": "zh-TW",

    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "日本語": "ja",
}


def _load_google_languages() -> Tuple[frozenset[str], dict[str, str]]:
    """Return (supported codes, code → English name) from Google Translate API."""
    global _GOOGLE_LANG_CACHE
    if _GOOGLE_LANG_CACHE is not None:
        return _GOOGLE_LANG_CACHE

    try:
        from gcs_translate import _get_client

        client = _get_client()
        langs = client.get_languages()
        codes = frozenset(entry["language"] for entry in langs)
        names = {entry["language"]: entry["name"] for entry in langs}
        _GOOGLE_LANG_CACHE = (codes, names)
        return _GOOGLE_LANG_CACHE
    except Exception as exc:
        print(f"WARNING: Could not load Google languages, using fallback set: {exc}")
        _GOOGLE_LANG_CACHE = (_FALLBACK_UI_LANGS, dict(_FALLBACK_LANG_NAMES))
        return _GOOGLE_LANG_CACHE


def get_supported_ui_langs() -> frozenset[str]:
    """Return UI language codes supported by Google Cloud Translation."""
    codes, _ = _load_google_languages()
    return codes


def _canonical_from_google(code: str) -> Optional[str]:
    """Match ``code`` against Google's language list (case-insensitive)."""
    codes, _ = _load_google_languages()
    needle = code.strip().replace("_", "-").lower()
    for supported in codes:
        if supported.lower() == needle:
            return supported
    primary = needle.split("-")[0]
    if primary != needle:
        for supported in codes:
            if supported.lower() == primary:
                return supported
    return None


def _finalize_ui_lang_code(canonical: Optional[str]) -> Optional[str]:
    """Map disallowed codes to supported equivalents (Simplified → Traditional)."""
    if canonical == "zh-CN":
        return "zh-TW"
    return canonical


def normalize_lang(code: Optional[str]) -> Optional[str]:
    """Normalize a user-supplied language code to a canonical supported code.

    Returns ``None`` if the code is empty or unrecognized. Simplified Chinese
    inputs (``zh-CN``, ``zh-hans``, etc.) normalize to ``zh-TW``.
    """
    if not code:
        return None

    key = code.strip().lower().replace(" ", "")
    alias_target = _ALIAS_MAP.get(key)
    if alias_target:
        canonical = _canonical_from_google(alias_target) or _canonical_from_google(code)
        if canonical:
            return _finalize_ui_lang_code(canonical)
        if alias_target in get_supported_ui_langs():
            return _finalize_ui_lang_code(alias_target)

    return _finalize_ui_lang_code(_canonical_from_google(code))


@lru_cache(maxsize=1)
def load_locale(lang: str = DEFAULT_LANG) -> dict:
    """Load English locale JSON (``lang`` is accepted for API compatibility)."""
    file_path = LOCALES_DIR / f"{DEFAULT_LANG}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_text(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Return English text for ``key`` with optional ``.format`` kwargs."""
    locale = load_locale()
    text = locale.get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def get_lang_display_name(lang: str, display_in: str = DEFAULT_LANG) -> str:
    """Return the human-readable name of ``lang`` from Google's language list."""
    canonical = normalize_lang(lang)
    if not canonical:
        return lang

    _, names = _load_google_languages()
    if canonical in names:
        return names[canonical]

    en_key = f"lang_name_{canonical}"
    en_name = get_text(en_key)
    if en_name != en_key:
        return en_name
    return canonical


def detect_ui_language(
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
    ui_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    platform_language_code: Optional[str] = None,
) -> str:
    """Pick the UI language to render messages in.

    Priority:
      1. Explicit ``ui_lang`` (stored setting or just-passed value).
      2. Inference from ``target_lang`` when it is a supported Google code.
      3. ``platform_language_code`` (e.g. Telegram ``from.language_code``).
      4. ``en``.

    ``user_id`` / ``group_id`` are accepted for call-site compatibility; settings
    lookup lives in each bot module so this function stays pure and testable.
    """
    canonical = normalize_lang(ui_lang)
    if canonical:
        return canonical

    if target_lang:
        inferred = normalize_lang(target_lang)
        if inferred:
            return inferred

    if platform_language_code:
        from_platform = normalize_lang(platform_language_code)
        if from_platform:
            return from_platform

    return DEFAULT_LANG


def _yes_no(value: bool, lang: str) -> str:
    return get_text("yes" if value else "no", lang)


def format_subscription_expiry(
    expires_at: Optional[Union[datetime, str]],
    lang: str = DEFAULT_LANG,
) -> str:
    """Format a subscription expiry datetime for display."""
    from datetime import timezone

    if expires_at is None:
        return get_text("subscription_no_expiry", lang)
    if isinstance(expires_at, str):
        normalized = expires_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    else:
        dt = expires_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def get_localized_status_lines(
    enabled: bool,
    mode: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    lang: str = DEFAULT_LANG,
    is_group: bool = False,
    is_thread: bool = False,
    ui_lang: Optional[str] = None,
) -> list[str]:
    """Render the ``/status`` body; dynamically translated when ``lang`` != ``en``."""
    en = DEFAULT_LANG
    if is_thread:
        title_key = "current_thread_settings"
    elif is_group:
        title_key = "current_group_settings"
    else:
        title_key = "current_user_settings"
    lines: list[str] = [get_text(title_key, en)]

    lines.append(f"{get_text('enabled', en)}: {_yes_no(enabled, en)}")
    lines.append(f"{get_text('mode', en)}: {mode}")

    if mode == "pair":
        src = source or get_text("not_set", en)
        tgt = target or get_text("not_set", en)
        lines.append(f"{get_text('languages', en)}: {src} <--> {tgt}")
    elif mode == "american":
        lines.append(f"{get_text('target', en)}: {get_text('target_american', en)}")
    elif mode == "mandarin":
        lines.append(f"{get_text('target', en)}: {get_text('target_mandarin', en)}")
    elif mode == "japanese":
        lines.append(f"{get_text('target', en)}: {get_text('target_japanese', en)}")

    if ui_lang:
        lines.append(
            f"{get_text('ui_language', en)}: "
            f"{get_lang_display_name(ui_lang, en)}"
        )

    canonical = normalize_lang(lang) or DEFAULT_LANG
    if canonical != DEFAULT_LANG:
        lines = translate_ui_lines(lines, canonical)
    return lines


def get_localized_subscription_status_lines(
    user_settings: Dict[str, Any],
    lang: str = DEFAULT_LANG,
    user_id: str = "",
    group_settings: Optional[Dict[str, Any]] = None,
    is_group: bool = False,
) -> list[str]:
    """Render ``/status subscription`` body as localized lines."""
    lines: list[str] = [get_text("subscription_status_title", lang)]

    personal = personal_subscription_from_settings(user_id, user_settings)
    personal_active = personal.is_active()
    lines.append(
        f"{get_text('subscription_personal_status', lang)}: "
        f"{get_text('subscription_active' if personal_active else 'subscription_inactive', lang)}"
    )
    if personal.plan_type:
        lines.append(
            f"{get_text('subscription_plan', lang)}: {personal.plan_type}"
        )
    if personal.subscribed or personal_active:
        lines.append(
            f"{get_text('subscription_expires', lang)}: "
            f"{format_subscription_expiry(personal.expires_at, lang)}"
        )

    if is_group and group_settings is not None:
        group = group_subscription_from_settings("", group_settings)
        group_active = group.is_active()
        lines.append(
            f"{get_text('subscription_group_status', lang)}: "
            f"{get_text('subscription_active' if group_active else 'subscription_inactive', lang)}"
        )
        if group.activated_by_user_id:
            lines.append(
                f"{get_text('subscription_activated_by', lang)}: "
                f"{group.activated_by_user_id}"
            )
        if group.activated_by_user_id or group_active:
            lines.append(
                f"{get_text('subscription_expires', lang)}: "
                f"{format_subscription_expiry(group.expires_at, lang)}"
            )

    return lines


def get_localized_help_lines(
    lang: str = DEFAULT_LANG,
    version: str = "unknown",
    platform: str = "LINE",
) -> list[str]:
    """Render the ``/help`` body; dynamically translated when ``lang`` != ``en``."""
    en = DEFAULT_LANG
    lines = [
        get_text("help_intro", en),
        "",
        get_text("help_commands_header", en),
        get_text("help_set_american", en),
        get_text("help_set_mandarin", en),
        get_text("help_set_japanese", en),
        get_text("help_set_pair", en),
        get_text("help_pair_options_header", en),
        get_text("help_pair_options", en),
        get_text("help_set_off", en),
        get_text("help_status", en),
        get_text("help_help", en),
        get_text("help_lang", en),
        get_text("help_subscribe", en),
        get_text("help_activate_group", en),
        get_text("help_status_subscription", en),
        "",
        get_text("help_voice_paid_only", en),
        "",
        get_text("help_version", en, version=version, platform=platform),
        "",
        get_text("help_copyright", en),
        get_text("help_website", en),
        "",
        get_text("help_translate_all_link", en),
    ]

    canonical = normalize_lang(lang) or DEFAULT_LANG
    if canonical != DEFAULT_LANG:
        lines = translate_ui_lines(lines, canonical)
    return lines


def supported_lang_codes() -> Iterable[str]:
    """Return canonical supported UI language codes (sorted, stable)."""
    return sorted(get_supported_ui_langs())
