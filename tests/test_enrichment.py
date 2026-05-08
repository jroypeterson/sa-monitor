"""Tests for halt-event enrichment (Phase 2 'Note:' context line)."""
import json
from pathlib import Path

import pytest

from src.calendars import AnalystDayCalendar, EarningsCalendar
from src.enrichment import build_note_context
from src.feeds.types import HaltEvent


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _halt(symbol="ITGR", halt_date="2026-04-30", halt_time="07:57:00"):
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date=halt_date, halt_time=halt_time,
        reason_code="T1", reason_description="News Pending",
        name="Integer Holdings", last_price=83.67, source="nasdaq_rss",
    )


def test_no_calendars_returns_none():
    assert build_note_context(_halt()) is None


def test_earnings_match_bmo(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "ITGR", "event_date": "2026-04-30",
                    "event_hour": "bmo", "tier": 2, "date_confirmed": True}],
    })
    cal = EarningsCalendar(p)
    note = build_note_context(_halt(), earnings=cal)
    assert note == "Note ITGR is scheduled to report earnings this morning"


def test_earnings_match_amc(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "AAPL", "event_date": "2026-05-08",
                    "event_hour": "amc", "tier": 1, "date_confirmed": True}],
    })
    cal = EarningsCalendar(p)
    note = build_note_context(
        _halt(symbol="AAPL", halt_date="2026-05-08", halt_time="16:25:00"),
        earnings=cal,
    )
    assert note == "Note AAPL is scheduled to report earnings this afternoon"


def test_earnings_no_event_hour_falls_back_to_halt_clock(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "AVDL", "event_date": "2026-05-05",
                    "event_hour": "", "tier": 3, "date_confirmed": False}],
    })
    cal = EarningsCalendar(p)
    morning = build_note_context(
        _halt(symbol="AVDL", halt_date="2026-05-05", halt_time="09:35:00"),
        earnings=cal,
    )
    assert morning == "Note AVDL is scheduled to report earnings this morning"
    afternoon = build_note_context(
        _halt(symbol="AVDL", halt_date="2026-05-05", halt_time="14:35:00"),
        earnings=cal,
    )
    assert afternoon == "Note AVDL is scheduled to report earnings this afternoon"


def test_earnings_different_day_no_match(tmp_path):
    p = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "ITGR", "event_date": "2026-05-01"}],
    })
    cal = EarningsCalendar(p)
    assert build_note_context(_halt(), earnings=cal) is None


def test_analyst_day_investor_day(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "AFRM", "company_name": "Affirm",
                    "event_type": "investor_day",
                    "start_date": "2026-05-12", "multi_day": False,
                    "status": "confirmed"}],
    })
    cal = AnalystDayCalendar(p)
    note = build_note_context(
        _halt(symbol="AFRM", halt_date="2026-05-12", halt_time="11:00:00"),
        analyst_days=cal,
    )
    assert note == "Note AFRM is hosting an investor day today"


def test_analyst_day_rd_day(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "GH", "event_type": "rd_day",
                    "start_date": "2026-06-15", "multi_day": False}],
    })
    cal = AnalystDayCalendar(p)
    note = build_note_context(
        _halt(symbol="GH", halt_date="2026-06-15", halt_time="10:00:00"),
        analyst_days=cal,
    )
    assert note == "Note GH is hosting an R&D day today"


def test_analyst_day_capital_markets_day_uses_a_article(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "BMY", "event_type": "capital_markets_day",
                    "start_date": "2026-06-15", "multi_day": False}],
    })
    cal = AnalystDayCalendar(p)
    note = build_note_context(
        _halt(symbol="BMY", halt_date="2026-06-15", halt_time="10:00:00"),
        analyst_days=cal,
    )
    assert note == "Note BMY is hosting a capital markets day today"


def test_analyst_day_conference(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "WST", "event_type": "conference",
                    "start_date": "2026-05-12", "multi_day": False}],
    })
    cal = AnalystDayCalendar(p)
    note = build_note_context(
        _halt(symbol="WST", halt_date="2026-05-12", halt_time="13:00:00"),
        analyst_days=cal,
    )
    assert note == "Note WST is presenting at an investor conference today"


def test_analyst_day_unknown_type_no_note(tmp_path):
    p = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "X", "event_type": "mystery",
                    "start_date": "2026-05-12"}],
    })
    cal = AnalystDayCalendar(p)
    assert build_note_context(
        _halt(symbol="X", halt_date="2026-05-12"), analyst_days=cal
    ) is None


def test_earnings_takes_priority_over_analyst_day(tmp_path):
    """If a ticker has BOTH an earnings event and an analyst-day on the same
    date, prefer the earnings note — it's higher-signal for halt context."""
    e = _write(tmp_path, "e.json", {
        "schema_version": 1,
        "events": [{"ticker": "X", "event_date": "2026-05-12",
                    "event_hour": "bmo"}],
    })
    a = _write(tmp_path, "ad.json", {
        "schema_version": 1,
        "events": [{"ticker": "X", "event_type": "investor_day",
                    "start_date": "2026-05-12"}],
    })
    note = build_note_context(
        _halt(symbol="X", halt_date="2026-05-12", halt_time="07:00:00"),
        earnings=EarningsCalendar(e),
        analyst_days=AnalystDayCalendar(a),
    )
    assert note == "Note X is scheduled to report earnings this morning"
