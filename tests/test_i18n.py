"""Tests for the i18n localization module.

Covers: English string lookups, normalization aliases, language detection,
dynamic /help and /status rendering (with mocked Google Translation).
"""

from unittest.mock import patch

import pytest

import i18n
from i18n import (
    DEFAULT_LANG,
    detect_ui_language,
    get_lang_display_name,
    get_localized_help_lines,
    get_localized_status_lines,
    get_supported_ui_langs,
    get_text,
    load_locale,
    normalize_lang,
    supported_lang_codes,
)


@pytest.fixture(autouse=True)
def reset_google_lang_cache():
    """Isolate tests from cached Google language data."""
    i18n._GOOGLE_LANG_CACHE = None
    load_locale.cache_clear()
    yield
    i18n._GOOGLE_LANG_CACHE = None
    load_locale.cache_clear()


@pytest.fixture(autouse=True)
def use_fallback_google_langs():
    """Use offline fallback language set (no GCP credentials in CI)."""
    i18n._GOOGLE_LANG_CACHE = (i18n._FALLBACK_UI_LANGS, dict(i18n._FALLBACK_LANG_NAMES))
    yield


# ---------- basic lookups ----------

def test_get_text_returns_english_by_default():
    assert get_text("help_title") == "Translator Bot Help"


def test_get_text_ignores_lang_param_and_returns_english():
    assert get_text("help_title", lang="zh-TW") == "Translator Bot Help"
    assert get_text("help_title", lang="ja") == "Translator Bot Help"


def test_get_text_supports_status_keys():
    assert get_text("status_title") == "Current Translation Settings:"


def test_get_text_falls_back_to_key_for_missing():
    assert get_text("__definitely_missing__", lang="ja") == "__definitely_missing__"


def test_get_text_format_kwargs():
    rendered = get_text("help_version", lang="en", version="1.2.3", platform="LINE")
    assert "1.2.3" in rendered and "LINE" in rendered


def test_get_text_format_with_bad_placeholder_does_not_crash():
    rendered = get_text("help_version", lang="en")
    assert "{version}" in rendered and "{platform}" in rendered


# ---------- normalization ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en", "en"),
        ("EN", "en"),
        ("English", "en"),
        ("zh-tw", "zh-TW"),
        ("ZH-TW", "zh-TW"),
        ("zh_tw", "zh-TW"),
        ("zh-Hant", "zh-TW"),
        ("tw", "zh-TW"),
        ("繁中", "zh-TW"),
        ("zh-cn", "zh-CN"),
        ("ZH-CN", "zh-CN"),
        ("zh_cn", "zh-CN"),
        ("zh-Hans", "zh-CN"),
        ("cn", "zh-CN"),
        ("simplified", "zh-CN"),
        ("简体中文", "zh-CN"),
        ("ja", "ja"),
        ("JA", "ja"),
        ("jp", "ja"),
        ("Japanese", "ja"),
        ("日本語", "ja"),
        ("ko", "ko"),
        ("es", "es"),
    ],
)
def test_normalize_lang_accepts_aliases_and_google_codes(raw, expected):
    assert normalize_lang(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "xx", "klingon"])
def test_normalize_lang_rejects_unsupported(raw):
    assert normalize_lang(raw) is None


def test_supported_lang_codes_matches_fallback_set():
    assert set(supported_lang_codes()) == set(get_supported_ui_langs())
    assert "en" in supported_lang_codes()
    assert "ko" in supported_lang_codes()
    assert "zh-CN" in supported_lang_codes()
    assert "zh-TW" in supported_lang_codes()


def test_load_locale_returns_english_dict():
    data = load_locale()
    assert isinstance(data, dict) and data
    assert "help_title" in data


# ---------- detection ----------

def test_detect_ui_language_returns_en_by_default():
    assert detect_ui_language(user_id="test-user-123") == "en"


def test_detect_ui_language_returns_zh_tw_when_set():
    assert detect_ui_language(user_id="test-user", ui_lang="zh-TW") == "zh-TW"


def test_detect_ui_language_returns_zh_cn_when_set():
    assert detect_ui_language(user_id="test-user", ui_lang="zh-CN") == "zh-CN"


def test_detect_ui_language_returns_ja_when_set():
    assert detect_ui_language(user_id="test-user", ui_lang="ja") == "ja"


def test_detect_ui_language_normalizes_input():
    assert detect_ui_language(ui_lang="JP") == "ja"
    assert detect_ui_language(ui_lang="zh_tw") == "zh-TW"
    assert detect_ui_language(ui_lang="zh_cn") == "zh-CN"


def test_detect_ui_language_infers_from_target_lang():
    assert detect_ui_language(target_lang="ja") == "ja"
    assert detect_ui_language(target_lang="ja-JP") == "ja"
    assert detect_ui_language(target_lang="zh-TW") == "zh-TW"
    assert detect_ui_language(target_lang="zh-CN") == "zh-CN"
    assert detect_ui_language(target_lang="ko") == "ko"


def test_detect_ui_language_explicit_beats_inferred():
    assert detect_ui_language(ui_lang="en", target_lang="ja") == "en"


def test_detect_ui_language_falls_back_for_unknown_target():
    assert detect_ui_language(target_lang="xx") == "en"


def test_detect_ui_language_from_platform_language_code():
    assert detect_ui_language(platform_language_code="ja") == "ja"
    assert detect_ui_language(platform_language_code="ja-JP") == "ja"
    assert detect_ui_language(platform_language_code="zh-hant") == "zh-TW"
    assert detect_ui_language(platform_language_code="zh-hans") == "zh-CN"


def test_detect_ui_language_target_beats_platform():
    assert detect_ui_language(target_lang="en", platform_language_code="ja") == "en"
    assert detect_ui_language(target_lang="ko", platform_language_code="ja") == "ko"


def test_detect_ui_language_explicit_beats_platform():
    assert detect_ui_language(ui_lang="en", platform_language_code="ja") == "en"


def test_detect_ui_language_platform_beats_default():
    assert detect_ui_language(platform_language_code="ja") == "ja"
    assert detect_ui_language(platform_language_code="klingon") == "en"


@pytest.mark.parametrize(
    "raw",
    [
        "zh-hant",
        "zh-TW",
        "zh_tw",
        "tw",
    ],
)
def test_normalize_lang_maps_traditional_chinese_to_zh_tw(raw):
    assert normalize_lang(raw) == "zh-TW"


@pytest.mark.parametrize(
    "raw",
    [
        "zh-hans",
        "zh-cn",
        "zh-CN",
        "zh_cn",
        "cn",
        "zh",
    ],
)
def test_normalize_lang_maps_simplified_chinese_to_zh_cn(raw):
    assert normalize_lang(raw) == "zh-CN"


# ---------- display names ----------

def test_get_lang_display_name_returns_google_names():
    assert get_lang_display_name("en") == "English"
    assert get_lang_display_name("zh-TW") == "Chinese (Traditional)"
    assert get_lang_display_name("zh-CN") == "Chinese (Simplified)"
    assert get_lang_display_name("ja") == "Japanese"
    assert get_lang_display_name("ko") == "Korean"


# ---------- status rendering ----------

def test_get_localized_status_lines_english_without_translation_call():
    lines = get_localized_status_lines(
        enabled=True, mode="pair", source="en", target="zh-TW", lang="en",
    )
    assert any("Current User" in line for line in lines)
    assert any("Yes" in line for line in lines)
    with patch("i18n.translate_ui_lines") as mock_translate:
        get_localized_status_lines(
            enabled=True, mode="pair", source="en", target="zh-TW", lang="en",
        )
        mock_translate.assert_not_called()


@patch("i18n.translate_ui_lines", side_effect=lambda lines, lang: [f"[{lang}]{line}" for line in lines])
def test_get_localized_status_lines_translates_when_not_english(mock_translate):
    lines = get_localized_status_lines(
        enabled=True, mode="pair", source="en", target="ja", lang="ja",
    )
    mock_translate.assert_called_once()
    assert lines[0].startswith("[ja]")


def test_get_localized_status_lines_group_title_in_english():
    lines = get_localized_status_lines(
        enabled=True, mode="pair", lang="en", is_group=True,
    )
    assert any("Group" in line for line in lines)


def test_get_localized_status_lines_thread_beats_group():
    lines = get_localized_status_lines(
        enabled=True, mode="pair", lang="en", is_group=True, is_thread=True,
    )
    assert any("Conversation" in line for line in lines)
    assert not any("Group" in line for line in lines)


# ---------- help rendering ----------

def test_get_localized_help_lines_english_without_translation_call():
    lines = get_localized_help_lines(lang="en", version="9.9.9", platform="LINE")
    assert any("Translator Bot" in line or "Add Translator Bot" in line for line in lines)
    assert any("9.9.9" in line for line in lines)
    with patch("i18n.translate_ui_lines") as mock_translate:
        get_localized_help_lines(lang="en", version="9.9.9", platform="LINE")
        mock_translate.assert_not_called()


@patch("i18n.translate_ui_lines", side_effect=lambda lines, lang: [f"[{lang}]{line}" for line in lines])
def test_get_localized_help_lines_translates_when_not_english(mock_translate):
    lines = get_localized_help_lines(lang="ko", version="1.0", platform="LINE")
    mock_translate.assert_called_once_with(mock_translate.call_args[0][0], "ko")
    assert any(line.startswith("[ko]") for line in lines)


def test_get_localized_help_lines_preserves_commands_in_english_source():
    lines = get_localized_help_lines(lang="en")
    assert any("/lang" in line for line in lines)
    assert any("/subscribe" in line for line in lines)
    assert any("/activate group" in line for line in lines)
    assert any("/status subscription" in line for line in lines)
    assert any("zh-CN" in line for line in lines)


def test_get_localized_help_lines_platform_is_threaded_through():
    lines_line = get_localized_help_lines(lang="en", version="1.0", platform="LINE")
    lines_tele = get_localized_help_lines(lang="en", version="1.0", platform="Telegram")
    assert any("LINE" in line for line in lines_line)
    assert any("Telegram" in line for line in lines_tele)


def test_get_localized_help_lines_telegram_has_voice_and_stars_commands():
    lines = get_localized_help_lines(lang="en", version="1.0", platform="Telegram")
    joined = "\n".join(lines)
    assert "/set voice" in joined
    assert "/terms" in joined
    assert "/paysupport" in joined
    assert "Stars" in joined
    assert "Voice-to-text is only available to paid customers!" not in joined


def test_get_localized_status_lines_includes_voice_when_provided():
    lines = get_localized_status_lines(
        enabled=True,
        mode="american",
        lang="en",
        voice_enabled=True,
        voice_gender="male",
        subscription_expires="2026-09-26 12:00 UTC",
    )
    joined = "\n".join(lines)
    assert "Spoken replies" in joined
    assert "male" in joined
    assert "2026-09-26" in joined


# ---------- error messages ----------

def test_err_unknown_ui_lang_mentions_bcp47():
    msg = get_text("err_unknown_ui_lang", lang="en", code="klingon")
    assert "klingon" in msg
    assert "BCP-47" in msg
