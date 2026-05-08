"""Tests for calendar loaders + indexing."""
import json
from pathlib import Path

import pytest

from src.calendars import AnalystDayCalendar, EarningsCalendar


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_earnings_calendar_loads_and_indexes(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "source": "earnings-agent",
        "generated_at": "2026-05-07T22:00:00Z",
        "events": [
            {"ticker": "ITGR", "event_date": "2026-04-30", "event_hour": "bmo",
             "tier": 2, "date_confirmed": True, "company_name": "Integer Holdings"},
            {"ticker": "AAPL", "event_date": "2026-05-08", "event_hour": "amc",
             "tier": 1, "date_confirmed": True, "company_name": "Apple Inc"},
        ],
    })
    cal = EarningsCalendar(p)
    assert cal.loaded_count == 2
    assert cal.generated_at == "2026-05-07T22:00:00Z"
    hit = cal.get("ITGR", "2026-04-30")
    assert hit is not None
    assert hit.event_hour == "bmo"
    assert hit.tier == 2
    assert cal.get("ITGR", "2026-05-01") is None  # different day, no match
    assert cal.get("nope", "2026-04-30") is None


def test_earnings_calendar_case_insensitive_ticker(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "itgr", "event_date": "2026-04-30", "event_hour": "bmo"}],
    })
    cal = EarningsCalendar(p)
    assert cal.get("ITGR", "2026-04-30") is not None
    assert cal.get("itgr", "2026-04-30") is not None


def test_earnings_calendar_missing_path_no_op():
    cal = EarningsCalendar(Path("/nonexistent/path/e.json"))
    assert cal.loaded_count == 0
    assert cal.get("AAPL", "2026-05-08") is None


def test_earnings_calendar_no_path_no_op():
    cal = EarningsCalendar(None)
    assert cal.loaded_count == 0
    assert cal.get("AAPL", "2026-05-08") is None


def test_earnings_calendar_wrong_schema_version_rejected(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 99,
        "events": [{"ticker": "AAPL", "event_date": "2026-05-08"}],
    })
    cal = EarningsCalendar(p)
    assert cal.loaded_count == 0


def test_earnings_calendar_skips_malformed_entries(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [
            {"ticker": "AAPL", "event_date": "2026-05-08"},  # ok
            {"ticker": "", "event_date": "2026-05-08"},      # blank ticker → skip
            {"ticker": "MSFT"},                               # no date → skip
        ],
    })
    cal = EarningsCalendar(p)
    assert cal.loaded_count == 1
    assert cal.get("AAPL", "2026-05-08") is not None


def test_analyst_day_calendar_single_day(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "source": "analyst-days",
        "events": [
            {"ticker": "AFRM", "company_name": "Affirm Holdings Inc",
             "event_type": "investor_day", "start_date": "2026-05-12",
             "end_date": None, "multi_day": False, "status": "confirmed"},
        ],
    })
    cal = AnalystDayCalendar(p)
    hit = cal.get("AFRM", "2026-05-12")
    assert hit is not None
    assert hit.event_type == "investor_day"
    assert cal.get("AFRM", "2026-05-13") is None  # outside the day


def test_analyst_day_calendar_multi_day_indexed_under_each_day(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [
            {"ticker": "WST", "company_name": "West Pharma",
             "event_type": "conference", "start_date": "2026-05-12",
             "end_date": "2026-05-14", "multi_day": True, "status": "confirmed"},
        ],
    })
    cal = AnalystDayCalendar(p)
    # Each day in the [start_date, end_date] window should resolve to the event.
    for day in ("2026-05-12", "2026-05-13", "2026-05-14"):
        hit = cal.get("WST", day)
        assert hit is not None, f"expected match on {day}"
        assert hit.event_type == "conference"
    assert cal.get("WST", "2026-05-15") is None
    assert cal.get("WST", "2026-05-11") is None


def test_analyst_day_calendar_missing_path_no_op():
    cal = AnalystDayCalendar(None)
    assert cal.get("AFRM", "2026-05-12") is None
    assert cal.loaded_count == 0


def test_analyst_day_calendar_malformed_dates_dont_crash(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [
            {"ticker": "X", "event_type": "investor_day",
             "start_date": "not-a-date", "end_date": "also-bad",
             "multi_day": True},
        ],
    })
    cal = AnalystDayCalendar(p)
    # malformed multi-day dates skip the secondary index but the entry still
    # registers under the primary key (start_date as written)
    assert cal.get("X", "not-a-date") is not None
