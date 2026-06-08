"""Tests for Telegram client language_code → UI language (Phase 2.5)."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("flask")

from i18n import detect_ui_language


def test_telegram_platform_language_helper_extracts_code():
    from telegram_translator_bot import _telegram_platform_language

    assert _telegram_platform_language({"language_code": "ja"}) == "ja"
    assert _telegram_platform_language({"language_code": "  zh-hant  "}) == "zh-hant"
    assert _telegram_platform_language({}) is None
    assert _telegram_platform_language(None) is None
    assert _telegram_platform_language({"language_code": ""}) is None


def test_resolve_ui_lang_uses_telegram_language_when_no_stored_pref(monkeypatch):
    from telegram_translator_bot import _resolve_ui_lang

    def fake_get_user_setting(user_id: str):
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None, "ui_lang": None}

    monkeypatch.setattr("telegram_translator_bot.get_user_setting", fake_get_user_setting)
    monkeypatch.setattr("telegram_translator_bot.get_thread_setting", fake_get_user_setting)

    ui = _resolve_ui_lang("user-1", thread_id=None, from_obj={"language_code": "ja"})
    assert ui == "ja"


def test_resolve_ui_lang_stored_ui_lang_beats_telegram_client(monkeypatch):
    from telegram_translator_bot import _resolve_ui_lang

    def fake_get_user_setting(user_id: str):
        return {"enabled": False, "mode": "pair", "source_lang": None, "target_lang": None, "ui_lang": "en"}

    monkeypatch.setattr("telegram_translator_bot.get_user_setting", fake_get_user_setting)

    ui = _resolve_ui_lang("user-1", from_obj={"language_code": "ja"})
    assert ui == "en"


def test_resolve_ui_lang_target_lang_beats_telegram_client(monkeypatch):
    from telegram_translator_bot import _resolve_ui_lang

    def fake_get_user_setting(user_id: str):
        return {
            "enabled": True,
            "mode": "pair",
            "source_lang": "en",
            "target_lang": "ko",
            "ui_lang": None,
        }

    monkeypatch.setattr("telegram_translator_bot.get_user_setting", fake_get_user_setting)

    ui = _resolve_ui_lang("user-1", from_obj={"language_code": "ja"})
    assert ui == "ko"
