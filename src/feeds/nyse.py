"""NYSE Trade Halt CSV feed parser.

Feed:     https://www.nyse.com/api/trade-halts/current/download
Format:   CSV (despite kickoff calling it JSON; reality is CSV)
Coverage: NYSE, NYSE American, NYSE Arca only. Excludes Nasdaq-listed names.
ToS:      Free, no auth.

CSV columns confirmed from public scrapes:
  Halt Date | Halt Time | Symbol | Name | Exchange | Reason | Resume Date | NYSE Resume Time

Times are Eastern Time. Dates are MM/DD/YYYY in the source.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Optional

import requests

from .types import HaltEvent
from ..reason_codes import describe, normalize_nyse_reason

log = logging.getLogger(__name__)

FEED_URL = "https://www.nyse.com/api/trade-halts/current/download"
USER_AGENT = "sa-monitor/0.1 (jroypeterson@gmail.com)"
TIMEOUT_SEC = 10


def _parse_date(date_str: str) -> str:
    """Source: 'MM/DD/YYYY'. Return ISO 'YYYY-MM-DD'."""
    if not date_str:
        return ""
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", date_str)
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
    return date_str.strip()


def _parse_time(time_str: str) -> str:
    """Source: 'HH:MM:SS' 24-hour. Trim and pass through."""
    return (time_str or "").strip()


def _parse_price(_: str) -> Optional[float]:
    """NYSE CSV doesn't include price columns in this endpoint; left as
    placeholder for forward-compat."""
    return None


def parse(csv_text: str) -> list[HaltEvent]:
    """Parse the NYSE current-halts CSV body into HaltEvent objects."""
    events: list[HaltEvent] = []
    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        halt_date = _parse_date(row.get("Halt Date") or "")
        halt_time = _parse_time(row.get("Halt Time") or "")
        reason_str = (row.get("Reason") or "").strip()
        reason_code = normalize_nyse_reason(reason_str)
        exchange = (row.get("Exchange") or "").strip() or "NYSE"

        if not symbol or not halt_date or not halt_time:
            log.warning(
                "nyse feed: skipping row missing symbol/date/time: %r", row
            )
            continue

        events.append(
            HaltEvent(
                symbol=symbol,
                exchange=exchange,
                halt_date=halt_date,
                halt_time=halt_time,
                reason_code=reason_code,
                reason_description=describe(reason_code) if reason_code in {
                    # Only translate codes we recognize; otherwise preserve
                    # the original NYSE reason string verbatim
                } else reason_str or describe(reason_code),
                name=(row.get("Name") or "").strip(),
                last_price=None,
                resume_date=_parse_date(row.get("Resume Date") or "") or None,
                resume_quote_time=None,
                resume_trade_time=_parse_time(row.get("NYSE Resume Time") or "")
                or None,
                source="nyse_csv",
                raw=dict(row),
            )
        )

    return events


def fetch(timeout: int = TIMEOUT_SEC) -> list[HaltEvent]:
    """Fetch the live NYSE current-halts CSV and return parsed HaltEvents."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv, application/csv, */*",
    }
    log.debug("nyse feed: fetching %s", FEED_URL)
    resp = requests.get(FEED_URL, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.text)
