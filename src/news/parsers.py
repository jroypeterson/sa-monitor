"""Shared utilities for news-wire RSS parsers.

Three concerns shared across PRN/BW/GNW:
- HTML→plain-text body cleaning (RSS descriptions are HTML/CDATA)
- RFC-822 date parsing (all three publish 'Fri, 8 May 2026 00:30:00 +0000')
- Ticker extraction from body text via exchange-prefix regex

Adapter modules import these instead of duplicating per-source. If a source
ever needs custom logic (e.g. PRN's industry tags vs BW's enclosures), keep
the source-specific bits in that module.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional


# Match (NASDAQ: ABCD), (Nasdaq:ABCD), (NYSE: ABCD), (NYSE Arca: ABCD), etc.
# Captures the ticker portion. Tickers include letters, digits, dots, dashes
# (for share-class suffixes like BRK.A), capped at 8 chars to avoid matching
# stray prose like "(NYSE: see story below)". Case-sensitive on the ticker so
# we don't match lowercase prose.
TICKER_RX = re.compile(
    r"\((?:NASDAQ|Nasdaq|NYSE\s+American|NYSE\s+Arca|NYSE|TSX|TSXV|OTCQB|OTCQX|NEO|CSE)\s*:\s*"
    r"([A-Z][A-Z0-9.\-]{0,7})\s*\)"
)

_TAG_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")


def strip_html(s: str) -> str:
    """Decode entities + remove tags + collapse whitespace.

    RSS bodies are HTML wrapped in CDATA. We don't try to preserve structure;
    matchers downstream want a flat plain-text blob.
    """
    if not s:
        return ""
    text = _TAG_RX.sub(" ", s)
    text = html.unescape(text)
    text = _WS_RX.sub(" ", text).strip()
    return text


def parse_pubdate(s: str) -> Optional[str]:
    """RFC 822 -> ISO 8601 UTC.

    Returns None on malformed input — the caller decides whether to skip the
    item or fall back to fetch time.
    """
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive timestamps as UTC — RSS feeds without tz are rare and
        # localizing them blind would be worse than this assumption.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds")


def extract_tickers(text: str) -> tuple[str, ...]:
    """Find exchange-prefix ticker mentions in text.

    Returns a deduped tuple, preserving first-seen order. Ignores tickers
    longer than 8 chars (defensive against prose collisions).
    """
    if not text:
        return ()
    seen: list[str] = []
    for m in TICKER_RX.finditer(text):
        t = m.group(1).upper()
        if t and t not in seen:
            seen.append(t)
    return tuple(seen)


def strip_ns(tag: str) -> str:
    """'{http://...}name' -> 'name' — for namespaced RSS elements."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
