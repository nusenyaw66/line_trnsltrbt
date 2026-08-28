"""Pair-mode matching for Simplified vs Traditional Chinese."""

from unittest.mock import MagicMock, patch

from gcs_translate import detect_and_translate


def _detect(language: str):
    mock_client = MagicMock()
    mock_client.detect_language.return_value = {"language": language}
    return mock_client


def test_pair_en_zh_cn_translates_simplified_to_english():
    with patch("gcs_translate._get_client", return_value=_detect("zh-CN")):
        with patch("gcs_translate.translate_text", return_value="hello") as mock_translate:
            result = detect_and_translate(
                "你好",
                enabled=True,
                source_lang="en",
                target_lang="zh-CN",
                mode="pair",
            )
    mock_translate.assert_called_once_with("你好", "en")
    assert result == "hello"


def test_pair_en_zh_cn_translates_english_to_simplified():
    with patch("gcs_translate._get_client", return_value=_detect("en")):
        with patch("gcs_translate.translate_text", return_value="你好") as mock_translate:
            result = detect_and_translate(
                "hello",
                enabled=True,
                source_lang="en",
                target_lang="zh-CN",
                mode="pair",
            )
    mock_translate.assert_called_once_with("hello", "zh-CN")
    assert result == "你好"


def test_pair_en_zh_tw_still_translates_simplified_input():
    """Traditional pair remains compatible with Simplified detection codes."""
    with patch("gcs_translate._get_client", return_value=_detect("zh-CN")):
        with patch("gcs_translate.translate_text", return_value="hello") as mock_translate:
            result = detect_and_translate(
                "你好",
                enabled=True,
                source_lang="en",
                target_lang="zh-TW",
                mode="pair",
            )
    mock_translate.assert_called_once_with("你好", "en")
    assert result == "hello"


def test_pair_zh_cn_zh_tw_translates_simplified_to_traditional():
    with patch("gcs_translate._get_client", return_value=_detect("zh-CN")):
        with patch("gcs_translate.translate_text", return_value="你好") as mock_translate:
            result = detect_and_translate(
                "你好",
                enabled=True,
                source_lang="zh-CN",
                target_lang="zh-TW",
                mode="pair",
            )
    mock_translate.assert_called_once_with("你好", "zh-TW")
    assert result == "你好"


def test_pair_zh_cn_zh_tw_translates_traditional_to_simplified():
    with patch("gcs_translate._get_client", return_value=_detect("zh-TW")):
        with patch("gcs_translate.translate_text", return_value="你好") as mock_translate:
            result = detect_and_translate(
                "你好",
                enabled=True,
                source_lang="zh-CN",
                target_lang="zh-TW",
                mode="pair",
            )
    mock_translate.assert_called_once_with("你好", "zh-CN")
    assert result == "你好"
