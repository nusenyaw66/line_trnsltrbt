"""Tests for the Telegram bot's parse_switch_command.

Mirrors test_parse_switch_command.py for the LINE bot. The Telegram bot
module validates a webhook secret + bot token at import time and pulls in
flask / google-cloud-*; we stub env and skip cleanly when deps aren't there.
"""

import os
import sys
from pathlib import Path

import pytest

# Required env vars for the Telegram bot to import without raising.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("flask")


def _parse(msg: str):
    from telegram_translator_bot import parse_switch_command
    return parse_switch_command(msg)


@pytest.mark.parametrize(
    "msg,expected_code",
    [
        ("/lang en", "en"),
        ("/lang zh-tw", "zh-tw"),
        ("/lang ja", "ja"),
        ("/lang JP", "jp"),
        ("/set lang en", "en"),
        ("/set lang zh-tw", "zh-tw"),
        ("/set lang ja", "ja"),
    ],
)
def test_parses_lang_commands(msg, expected_code):
    assert _parse(msg) == {"type": "set_lang", "code": expected_code}


def test_lang_without_arg_is_not_a_command():
    assert _parse("/lang") is None


def test_set_lang_without_arg_is_not_a_command():
    assert _parse("/set lang") is None


def test_existing_commands_still_parse():
    assert _parse("/help") == {"type": "help"}
    assert _parse("/status") == {"type": "status"}
    assert _parse("/set on") == {"type": "set_on"}
    assert _parse("/set off") == {"type": "set_off"}
    assert _parse("/set american") == {"type": "set_american"}
    assert _parse("/set mandarin") == {"type": "set_mandarin"}
    assert _parse("/set japanese") == {"type": "set_japanese"}
    assert _parse("/set pair en zh-tw") == {
        "type": "set_pair", "source": "en", "target": "zh-tw",
    }


def test_non_command_returns_none():
    assert _parse("hello there") is None
    assert _parse("") is None
    assert _parse("/unknownthing") is None
