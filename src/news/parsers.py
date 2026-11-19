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
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from ..feeds.types import FeedParseError

# Root elements a syndication document can have (RSS 2.0, Atom, RSS 1.0/RDF).
_FEED_ROOTS = {"rss", "feed", "rdf"}


def require_feed_shape(content: bytes, source: str) -> None:
    """Raise FeedParseError unless `content` is a feed document with >= 1 <item>.

    A news wire can answer HTTP 200 with an HTML maintenance page, a WAF or CDN
    challenge, or a truncated body. The adapters' parse() is deliberately
    tolerant and turns all of those into [], which _safe_fetch would count as a
    healthy, empty poll — so a dead wire would never reach the failure counter
    or the failure DM. The halt adapters got this same guard in fetch()
    (feeds/nasdaq.py); this is the news-wire equivalent. It belongs in fetch(),
    never parse(): parse() tolerance is pinned by tests.

    Zero <item> elements also fails: these wires always carry their latest
    releases, so an itemless channel is a soft failure, not a quiet hour.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise FeedParseError(
            f"{source} feed: 200 response is not valid XML ({e}); "
            f"likely an HTML error/challenge page"
        ) from e
    root_name = strip_ns(root.tag).lower()
    if root_name not in _FEED_ROOTS:
        raise FeedParseError(
            f"{source} feed: unexpected root <{strip_ns(root.tag)}> "
            f"(expected rss/feed/RDF); likely a soft-failed response"
        )
    if not any(strip_ns(node.tag) == "item" for node in root.iter()):
        raise FeedParseError(
            f"{source} feed: 200 response has no <item> elements; "
            f"likely a soft-failed or truncated response"
        )


def require_items(items: list, source: str) -> list:
    """Raise FeedParseError when a well-formed feed yielded no usable record.

    require_feed_shape() only proves an <item> element exists. A truncated or
    soft-failed body can carry items that parse() skips (no title or no link),
    and an empty result would again read as a healthy, quiet wire.
    """
    if not items:
        raise FeedParseError(
            f"{source} feed: <item> elements present but none parsed into a "
            f"usable record (missing title/link); likely a soft-failed response"
        )
    return items


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
