"""Runtime Google Translation for bot UI strings (/help, /status).

English source text is composed from ``locales/en.json``, then translated via
``gcs_translate.translate_text`` when ``ui_lang`` is not ``en``. Non-translatable
segments (slash commands, URLs, language codes) are masked before translation.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from gcs_translate import translate_text

_PLACEHOLDER = "⟦{i}⟧"

# Order matters: more specific patterns before general ones.
_MASK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://[^\s]+"),
    re.compile(r"www\.[^\s]+"),
    re.compile(r'"[^"]+"'),
    re.compile(
        r"/(?:[\w]+(?:\s+(?:[\w]+|<[^>]+>))+|[\w]+)(?=\s+-|\s*$|\n|\s*,)"
    ),
    re.compile(r"/[\w]+(?:\s+[\w]+)*"),
    re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"),
    re.compile(r"<-->"),
    re.compile(
        r"\b(?:en-US|zh-TW|zh-tw|zh-CN|zh-cn|tw|cn|en|ja|ko|th|id|fil|vi|fr|de|it|es)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:pair|american|mandarin|japanese)\b"),
    re.compile(r"\b(?:LINE|Telegram|Messenger)\b"),
)


def _collect_spans(text: str) -> list[tuple[int, int]]:
    """Return non-overlapping (start, end) spans to mask, left-to-right."""
    spans: list[tuple[int, int]] = []
    for pattern in _MASK_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(not (end <= s or start >= e) for s, e in spans):
                continue
            spans.append((start, end))
    spans.sort(key=lambda s: s[0])
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def mask_non_translatable(text: str) -> Tuple[str, List[str]]:
    """Replace non-translatable segments with numbered placeholders."""
    spans = _collect_spans(text)
    if not spans:
        return text, []

    placeholders: list[str] = []
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        placeholders.append(text[start:end])
        parts.append(_PLACEHOLDER.format(i=len(placeholders) - 1))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), placeholders


def unmask_translated(text: str, placeholders: List[str]) -> str:
    """Restore masked segments after translation."""
    for i, original in enumerate(placeholders):
        text = text.replace(_PLACEHOLDER.format(i=i), original)
    return text


def translate_ui_text(text: str, target_lang: str) -> str:
    """Translate UI text to ``target_lang``, preserving commands and URLs."""
    if not text.strip():
        return text
    masked, placeholders = mask_non_translatable(text)
    try:
        translated = translate_text(masked, target_lang)
    except Exception as exc:
        print(f"ERROR in translate_ui_text: {exc}")
        return text
    return unmask_translated(translated, placeholders)


def translate_ui_lines(lines: List[str], target_lang: str) -> List[str]:
    """Translate a list of UI lines in one API call; fall back to English on failure."""
    if target_lang.lower() in ("en", "en-us"):
        return lines
    if not lines:
        return lines

    joined = "\n".join(lines)
    try:
        translated = translate_ui_text(joined, target_lang)
    except Exception as exc:
        print(f"ERROR in translate_ui_lines: {exc}")
        return lines

    result = translated.split("\n")
    if len(result) != len(lines):
        # Newline count changed; return best-effort split or English fallback.
        if len(result) == 1 and len(lines) > 1:
            return lines
    return result
