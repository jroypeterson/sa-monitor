"""Tests for halt-event enrichment (Phase 2 'Note:' context line)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.calendars import AnalystDayCalendar, EarningsCalendar
from src.enrichment import build_note_context
from src.feeds.types import HaltEvent
from src.news.cache import NewsCache
from src.news.types import NewsItem


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


def test_cross_ref_note_renders_press_release_summary():
    """A halt with a coincident PR Newswire press release should produce a
    'Follows ... press release: ...' note."""
    halt = HaltEvent(
        symbol="NKTR", exchange="Nasdaq", halt_date="2026-05-07",
        halt_time="07:25:00", reason_code="T1", reason_description="News Pending",
        name="Nektar Therapeutics", source="nasdaq_rss",
    )
    cache = NewsCache()
    # 07:25 ET = 11:25 UTC (EDT). News published 5 min earlier.
    halt_utc = datetime(2026, 5, 7, 11, 25, tzinfo=timezone.utc)
    cache.ingest([NewsItem(
        source="prnewswire",
        title="Nektar Therapeutics Reports First Quarter 2026 Financial Results",
        body="b", url="https://prn.test/nktr",
        published_at="2026-05-07T11:20:00+00:00",
        tickers=("NKTR",),
    )], now_utc=halt_utc)
    note = build_note_context(halt, news_cache=cache)
    assert note == (
        "Follows PR Newswire press release: "
        "Nektar Therapeutics Reports First Quarter 2026 Financial Results"
    )


def test_cross_ref_note_picks_newest_when_multiple():
    halt = HaltEvent(
        symbol="X", exchange="Nasdaq", halt_date="2026-05-07", halt_time="07:30:00",
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )
    cache = NewsCache()
    halt_utc = datetime(2026, 5, 7, 11, 30, tzinfo=timezone.utc)
    cache.ingest([
        NewsItem(source="prnewswire", title="older PR", body="b",
                 url="https://x.test/old", published_at="2026-05-07T11:00:00+00:00",
                 tickers=("X",)),
        NewsItem(source="businesswire", title="newest PR", body="b",
                 url="https://x.test/new", published_at="2026-05-07T11:25:00+00:00",
                 tickers=("X",)),
    ], now_utc=halt_utc)
    note = build_note_context(halt, news_cache=cache)
    assert note == "Follows Business Wire press release: newest PR"


def test_cross_ref_takes_priority_over_earnings(tmp_path):
    """If a ticker has both a same-day earnings event AND a coincident PR
    cross-ref, the cross-ref note wins — it's a more specific signal."""
    halt = HaltEvent(
        symbol="X", exchange="Nasdaq", halt_date="2026-05-08", halt_time="07:00:00",
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )
    e_path = tmp_path / "e.json"
    e_path.write_text(json.dumps({
        "schema_version": 1,
        "events": [{"ticker": "X", "event_date": "2026-05-08", "event_hour": "bmo"}],
    }), encoding="utf-8")
    cache = NewsCache()
    halt_utc = datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc)
    cache.ingest([NewsItem(
        source="prnewswire", title="X Reports Q1 results", body="b",
        url="https://x.test/q1", published_at="2026-05-08T10:55:00+00:00",
        tickers=("X",),
    )], now_utc=halt_utc)
    note = build_note_context(halt, earnings=EarningsCalendar(e_path), news_cache=cache)
    assert note.startswith("Follows ")
    assert "earnings" not in note


def test_cross_ref_falls_through_to_earnings_when_no_news_match(tmp_path):
    halt = HaltEvent(
        symbol="X", exchange="Nasdaq", halt_date="2026-05-08", halt_time="07:00:00",
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )
    e_path = tmp_path / "e.json"
    e_path.write_text(json.dumps({
        "schema_version": 1,
        "events": [{"ticker": "X", "event_date": "2026-05-08", "event_hour": "bmo"}],
    }), encoding="utf-8")
    cache = NewsCache()  # empty cache
    note = build_note_context(halt, earnings=EarningsCalendar(e_path), news_cache=cache)
    assert note == "Note X is scheduled to report earnings this morning"


def test_cross_ref_long_title_is_truncated_with_ellipsis():
    halt = HaltEvent(
        symbol="X", exchange="Nasdaq", halt_date="2026-05-07", halt_time="08:00:00",
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )
    cache = NewsCache()
    halt_utc = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    long_title = "X " * 100  # ~200 chars
    cache.ingest([NewsItem(
        source="prnewswire", title=long_title.strip(), body="b",
        url="https://x.test/long", published_at="2026-05-07T11:55:00+00:00",
        tickers=("X",),
    )], now_utc=halt_utc)
    note = build_note_context(halt, news_cache=cache)
    assert note.endswith("…")
    assert len(note) < 200  # capped


def test_no_news_cache_returns_calendar_note(tmp_path):
    """Slice 1 callers (no news_cache passed) still work."""
    halt = HaltEvent(
        symbol="X", exchange="Nasdaq", halt_date="2026-05-08", halt_time="07:00:00",
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )
    e_path = tmp_path / "e.json"
    e_path.write_text(json.dumps({
        "schema_version": 1,
        "events": [{"ticker": "X", "event_date": "2026-05-08", "event_hour": "bmo"}],
    }), encoding="utf-8")
    note = build_note_context(halt, earnings=EarningsCalendar(e_path))
    assert note == "Note X is scheduled to report earnings this morning"


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
