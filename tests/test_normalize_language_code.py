"""Tests for normalize_language_code across bot modules."""

import pytest

from line_translator_bot import normalize_language_code as line_normalize
from messenger_translator_bot import normalize_language_code as messenger_normalize
from telegram_translator_bot import normalize_language_code as telegram_normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("zh-TW", "zh-TW"),
        ("zh-tw", "zh-TW"),
        ("zh-cn", "zh-TW"),
        ("zh-hans", "zh-TW"),
        ("zh-hant", "zh-TW"),
        ("tw", "zh-TW"),
        ("TW", "zh-TW"),
        ("en", "en"),
        ("ja", "ja"),
    ],
)
@pytest.mark.parametrize(
    "normalize_fn",
    [line_normalize, telegram_normalize, messenger_normalize],
)
def test_normalize_language_code_accepts_tw_for_mandarin(raw, expected, normalize_fn):
    assert normalize_fn(raw) == expected
