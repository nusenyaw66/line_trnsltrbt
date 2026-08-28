"""Tests for runtime UI translation (masking, batching, fallback)."""

from unittest.mock import patch

import pytest

from ui_translate import (
    mask_non_translatable,
    translate_ui_lines,
    translate_ui_text,
    unmask_translated,
)


def test_mask_preserves_slash_commands():
    text = "/set pair <lang1> <lang2> - sets specific language pair"
    masked, placeholders = mask_non_translatable(text)
    assert "/set pair" not in masked or "⟦" in masked
    assert len(placeholders) >= 1
    assert any("/set pair" in p for p in placeholders)
    restored = unmask_translated(masked, placeholders)
    assert restored == text


def test_mask_preserves_urls():
    text = "See https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types for info."
    masked, placeholders = mask_non_translatable(text)
    assert "https://docs.cloud.google.com" not in masked
    restored = unmask_translated(masked, placeholders)
    assert restored == text


def test_mask_preserves_quoted_language_codes():
    text = '   "zh-TW"  # Mandarin, "zh-CN"  # Simplified, "ja"  # Japanese'
    masked, placeholders = mask_non_translatable(text)
    assert '"zh-TW"' not in masked
    assert '"zh-CN"' not in masked
    restored = unmask_translated(masked, placeholders)
    assert restored == text


@patch("ui_translate.translate_text", side_effect=lambda text, lang: f"[{lang}]{text}")
def test_translate_ui_text_restores_masked_segments(mock_translate):
    text = "/help - returns this help message"
    result = translate_ui_text(text, "ko")
    mock_translate.assert_called_once()
    assert "/help" in result
    assert result.endswith("/help - returns this help message") or "/help" in result


@patch("ui_translate.translate_text", side_effect=lambda text, lang: text)
def test_translate_ui_lines_returns_english_for_en(mock_translate):
    lines = ["Line one", "Line two"]
    assert translate_ui_lines(lines, "en") == lines
    mock_translate.assert_not_called()


@patch(
    "ui_translate.translate_text",
    side_effect=lambda text, lang: "\n".join(
        f"[{lang}]{line}" for line in text.split("\n")
    ),
)
def test_translate_ui_lines_batches_with_newlines(mock_translate):
    lines = ["Alpha", "Beta", "Gamma"]
    result = translate_ui_lines(lines, "ja")
    mock_translate.assert_called_once_with("Alpha\nBeta\nGamma", "ja")
    assert len(result) == 3
    assert all(line.startswith("[ja]") for line in result)


@patch("ui_translate.translate_text", side_effect=RuntimeError("API down"))
def test_translate_ui_lines_falls_back_to_english(mock_translate):
    lines = ["Hello", "World"]
    assert translate_ui_lines(lines, "ko") == lines


@patch("ui_translate.translate_text", side_effect=lambda text, lang: "single line only")
def test_translate_ui_lines_falls_back_when_line_count_changes(mock_translate):
    lines = ["One", "Two", "Three"]
    assert translate_ui_lines(lines, "es") == lines
