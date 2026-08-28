"""Optional live smoke test against GEMINI_API_KEY + GOOGLE_GEMINI_BASE_URL."""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from gemini_voice import smoke_test_proxy


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; skipping live proxy smoke test",
)
def test_gemini_proxy_generate_content_smoke():
    result = smoke_test_proxy()
    assert result["ok"] is True
    assert result["text"]
