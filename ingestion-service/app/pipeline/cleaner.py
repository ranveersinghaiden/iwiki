"""HTML → clean plain text / markdown converter."""
from __future__ import annotations

import re

import bleach
import markdownify


def clean_html(html: str) -> str:
    """Convert HTML to clean, readable markdown text."""
    if not html:
        return ""
    # Convert to markdown (preserves headings, lists, code blocks)
    md = markdownify.markdownify(html, heading_style="ATX", strip=["script", "style"])
    return _normalise(md)


def clean_text(text: str) -> str:
    """Normalise plain text (strip extra whitespace, blank lines)."""
    if not text:
        return ""
    return _normalise(text)


def strip_html(html: str) -> str:
    """Hard-strip all HTML tags — use when markdown conversion isn't needed."""
    if not html:
        return ""
    stripped = bleach.clean(html, tags=[], attributes={}, strip=True)
    return _normalise(stripped)


def _normalise(text: str) -> str:
    # Collapse 3+ consecutive newlines → 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces/tabs into single space (but keep newlines)
    text = re.sub(r"[ \t]+", " ", text)
    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()

