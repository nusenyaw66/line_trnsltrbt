"""Tests for parse_switch_command (focus: /lang and /set lang additions).

Imports parse_switch_command without booting the full bot by stubbing the
LINE credentials env vars first.
"""

import os
import sys
from pathlib import Path

import pytest

# The bot module validates LINE credentials at import time; provide harmless
# values so we can import the parsing function.
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

# These tests exercise the bot's command parser. The bot module pulls in
# Flask, the LINE SDK, and google-cloud-* at import time; skip the file
# cleanly when those aren't installed (e.g. minimal CI lanes).
pytest.importorskip("flask")
pytest.importorskip("linebot")


def _parse(msg: str):
    # Imported lazily so credential env vars are in place first.
    from line_translator_bot import parse_switch_command
    return parse_switch_command(msg)


@pytest.mark.parametrize(
    "msg,expected_code",
    [
        ("/lang en", "en"),
        ("/lang zh-tw", "zh-tw"),
        ("/lang ja", "ja"),
        ("/lang JP", "jp"),  # parser lowercases; normalization happens in handler
        ("/set lang en", "en"),
        ("/set lang zh-tw", "zh-tw"),
        ("/set lang ja", "ja"),
    ],
)
def test_parses_lang_commands(msg, expected_code):
    info = _parse(msg)
    assert info == {"type": "set_lang", "code": expected_code}


def test_lang_without_arg_is_not_a_command():
    assert _parse("/lang") is None


def test_set_lang_without_arg_is_not_a_command():
    assert _parse("/set lang") is None


def test_existing_commands_still_parse():
    assert _parse("/help") == {"type": "help"}
    assert _parse("/status") == {"type": "status"}
    assert _parse("/status subscription") == {"type": "status_subscription"}
    assert _parse("/subscribe") == {"type": "subscribe"}
    assert _parse("/activate group") == {"type": "activate_group"}
    assert _parse("/set on") == {"type": "set_on"}
    assert _parse("/set off") == {"type": "set_off"}
    assert _parse("/set american") == {"type": "set_american"}
    assert _parse("/set mandarin") == {"type": "set_mandarin"}
    assert _parse("/set japanese") == {"type": "set_japanese"}
    assert _parse("/set pair en zh-tw") == {
        "type": "set_pair", "source": "en", "target": "zh-tw",
    }
