"""Calendar loaders for sa-monitor halt enrichment (Phase 2).

Two calendar feeds power the "Note:" context line on halt alerts:

1. Earnings calendar — published by sibling `earnings-agent` repo as
   `exports/upcoming_events.json`. Source-of-truth for which tickers have
   earnings calls scheduled in the upcoming ~14d window.
2. Analyst-days calendar — published by sibling `analyst-days` repo as
   `exports/upcoming_events.json`. Source-of-truth for investor/R&D/
   capital-markets days and tracked conferences.

Both feeds use a small, stable JSON schema (see EarningsCalendar.SCHEMA_VERSION
+ AnalystDayCalendar.SCHEMA_VERSION). If a calendar file is missing, empty,
or malformed, the calendar loads as empty and enrichment becomes a no-op for
that source — sa-monitor must not fail open on missing calendars.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    event_date: str          # ISO YYYY-MM-DD (in ET)
    event_hour: str          # 'bmo' | 'amc' | ''
    tier: int                # 1=high confidence, 3=low (per earnings-agent schema)
    date_confirmed: bool
    call_datetime_utc: Optional[str]
    company_name: str


@dataclass(frozen=True)
class AnalystDayEvent:
    ticker: str
    company_name: str
    event_type: str          # 'investor_day' | 'rd_day' | 'analyst_day' | 'capital_markets_day' | 'conference'
    start_date: str          # ISO YYYY-MM-DD
    end_date: Optional[str]
    multi_day: bool
    status: str              # 'confirmed' | 'tentative' | etc.


class _BaseCalendar:
    """Common load + indexing logic. Not instantiated directly."""

    SCHEMA_VERSION = 1
    SOURCE = ""  # subclass override

    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self._by_ticker_date: dict[tuple[str, str], object] = {}
        self._generated_at: Optional[str] = None
        self._loaded_count = 0
        if path is not None:
            self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            log.info("%s calendar not found at %s; enrichment will no-op", self.SOURCE, path)
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("%s calendar at %s failed to parse: %s", self.SOURCE, path, exc)
            return
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            log.error("%s calendar at %s has schema_version=%s, expected %s",
                      self.SOURCE, path, payload.get("schema_version"), self.SCHEMA_VERSION)
            return
        self._generated_at = payload.get("generated_at")
        for raw in payload.get("events", []):
            entry = self._parse_entry(raw)
            if entry is None:
                continue
            key = self._key_for(entry)
            self._by_ticker_date[key] = entry
            self._loaded_count += 1

    # subclass hooks
    def _parse_entry(self, raw: dict) -> Optional[object]:
        raise NotImplementedError

    def _key_for(self, entry: object) -> tuple[str, str]:
        raise NotImplementedError

    @property
    def loaded_count(self) -> int:
        return self._loaded_count

    @property
    def generated_at(self) -> Optional[str]:
        return self._generated_at


class EarningsCalendar(_BaseCalendar):
    SOURCE = "earnings"

    def _parse_entry(self, raw: dict) -> Optional[EarningsEvent]:
        ticker = (raw.get("ticker") or "").upper()
        event_date = raw.get("event_date") or ""
        if not ticker or not event_date:
            return None
        return EarningsEvent(
            ticker=ticker,
            event_date=event_date,
            event_hour=(raw.get("event_hour") or "").lower(),
            tier=int(raw.get("tier") or 0),
            date_confirmed=bool(raw.get("date_confirmed")),
            call_datetime_utc=raw.get("call_datetime_utc"),
            company_name=raw.get("company_name") or "",
        )

    def _key_for(self, entry: EarningsEvent) -> tuple[str, str]:
        return (entry.ticker, entry.event_date)

    def get(self, ticker: str, on_date: str) -> Optional[EarningsEvent]:
        return self._by_ticker_date.get((ticker.upper(), on_date))


class AnalystDayCalendar(_BaseCalendar):
    SOURCE = "analyst-days"

    def __init__(self, path: Optional[Path] = None):
        # secondary index — multi-day events register under each day they cover
        self._by_ticker_date_multi: dict[tuple[str, str], list[AnalystDayEvent]] = {}
        super().__init__(path)

    def _parse_entry(self, raw: dict) -> Optional[AnalystDayEvent]:
        ticker = (raw.get("ticker") or "").upper()
        start_date = raw.get("start_date") or ""
        if not ticker or not start_date:
            return None
        return AnalystDayEvent(
            ticker=ticker,
            company_name=raw.get("company_name") or "",
            event_type=raw.get("event_type") or "",
            start_date=start_date,
            end_date=raw.get("end_date"),
            multi_day=bool(raw.get("multi_day")),
            status=raw.get("status") or "",
        )

    def _key_for(self, entry: AnalystDayEvent) -> tuple[str, str]:
        # Register under start_date (single-day) or each day in [start_date, end_date]
        # (multi-day). _by_ticker_date holds the start_date entry; secondary index
        # holds all days for multi-day events.
        primary = (entry.ticker, entry.start_date)
        if entry.multi_day and entry.end_date:
            from datetime import date, timedelta
            try:
                d0 = date.fromisoformat(entry.start_date)
                d1 = date.fromisoformat(entry.end_date)
                cur = d0
                while cur <= d1:
                    self._by_ticker_date_multi.setdefault(
                        (entry.ticker, cur.isoformat()), []
                    ).append(entry)
                    cur += timedelta(days=1)
            except ValueError:
                pass
        return primary

    def get(self, ticker: str, on_date: str) -> Optional[AnalystDayEvent]:
        key = (ticker.upper(), on_date)
        # check single-day index first
        entry = self._by_ticker_date.get(key)
        if entry is not None:
            return entry  # type: ignore[return-value]
        # fall back to multi-day coverage
        multi = self._by_ticker_date_multi.get(key)
        if multi:
            return multi[0]
        return None
