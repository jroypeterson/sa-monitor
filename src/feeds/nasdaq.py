"""Nasdaq Trader Trade Halt RSS feed parser.

Feed:    https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts
Format:  RSS 2.0 XML with custom <ndaq:*> namespace fields per item
Coverage: All SRO-listed US equities (Nasdaq + NYSE + NYSE American + NYSE Arca
          + Cboe BZX + IEX) — Nasdaq operates this as the UTP/CQS halt-of-record
ToS:     Free, no auth. See nasdaqtrader.com THRSSFeedTermsCond.pdf
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import requests

from .types import HaltEvent
from ..reason_codes import describe

log = logging.getLogger(__name__)

FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
USER_AGENT = "sa-monitor/0.1 (jroypeterson@gmail.com)"
TIMEOUT_SEC = 10

# Custom namespace seen in nasdaqtrader's RSS feed for trade halts.
# Confirmed against community parsers; subject to verification once the
# feed is reached live.
NS = {
    "ndaq": "http://www.nasdaqtrader.com/",
}


def _strip_ns(tag: str) -> str:
    """ '{http://www.nasdaqtrader.com/}IssueSymbol' -> 'IssueSymbol' """
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_date(date_str: str) -> str:
    """Nasdaq publishes 'MM/DD/YYYY'. Return ISO 'YYYY-MM-DD'."""
    if not date_str:
        return ""
    try:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str.strip())
        if m:
            mm, dd, yyyy = m.groups()
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
    except Exception:
        pass
    return date_str  # leave as-is if unparseable; downstream can decide


def _parse_time(time_str: str) -> str:
    """Nasdaq publishes 'HH:MM:SS' (24-hour). Pass through after trim."""
    return (time_str or "").strip()


def _parse_price(price_str: str) -> Optional[float]:
    """Nasdaq RSS doesn't include price; NYSE CSV does. This is here for
    forward-compat in case the schema changes."""
    if not price_str:
        return None
    try:
        return float(price_str.replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse(xml_bytes: bytes) -> list[HaltEvent]:
    """Parse a Nasdaq Trader Trade Halt RSS feed into HaltEvent objects.

    Designed to be tolerant of feed-shape variations: we extract by tag-name
    after stripping namespace, so the parser works whether the namespace is
    declared or not. Items missing required fields (symbol, date, time) are
    logged and skipped, not raised — the runtime polling loop should not die
    on one malformed item.
    """
    events: list[HaltEvent] = []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.error("nasdaq feed: XML parse error: %s", e)
        return events

    # RSS structure: <rss><channel><item>...</item></channel></rss>
    for item in root.iter():
        if _strip_ns(item.tag) != "item":
            continue

        fields: dict[str, str] = {}
        for child in item:
            name = _strip_ns(child.tag)
            text = (child.text or "").strip()
            if name and text:
                fields[name] = text

        symbol = fields.get("IssueSymbol") or fields.get("Symbol") or ""
        halt_date = _parse_date(fields.get("HaltDate", ""))
        halt_time = _parse_time(fields.get("HaltTime", ""))
        reason_code = (fields.get("ReasonCode") or "").upper()

        if not symbol or not halt_date or not halt_time:
            log.warning(
                "nasdaq feed: skipping item missing symbol/date/time: %r", fields
            )
            continue

        events.append(
            HaltEvent(
                symbol=symbol,
                exchange=fields.get("Market", "") or "Nasdaq",
                halt_date=halt_date,
                halt_time=halt_time,
                reason_code=reason_code,
                reason_description=describe(reason_code),
                name=fields.get("IssueName", "") or fields.get("CompanyName", ""),
                last_price=None,
                resume_date=_parse_date(fields.get("ResumptionDate", "")) or None,
                resume_quote_time=_parse_time(fields.get("ResumptionQuoteTime", ""))
                or None,
                resume_trade_time=_parse_time(fields.get("ResumptionTradeTime", ""))
                or None,
                source="nasdaq_rss",
                raw=fields,
            )
        )

    return events


def fetch(timeout: int = TIMEOUT_SEC) -> list[HaltEvent]:
    """Fetch the live Nasdaq RSS feed and return parsed HaltEvents.
    Raises on network error so the caller can decide on retry/backoff."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    log.debug("nasdaq feed: fetching %s", FEED_URL)
    resp = requests.get(FEED_URL, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.content)
