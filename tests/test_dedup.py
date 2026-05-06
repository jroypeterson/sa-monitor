"""Tests for the HaltTracker dedup logic."""
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent


def make_event(symbol="VRDN", date="2026-05-05", time="06:55:32",
               resume_trade_time=None):
    return HaltEvent(
        symbol=symbol,
        exchange="Nasdaq",
        halt_date=date,
        halt_time=time,
        reason_code="T1",
        reason_description="News Pending",
        resume_trade_time=resume_trade_time,
        source="nasdaq_rss",
    )


def test_first_sighting_emits_halt():
    tracker = HaltTracker()
    event = make_event()
    out = list(tracker.ingest([event]))
    assert len(out) == 1
    assert out[0] == ("halt", event)


def test_repeat_poll_no_emit():
    tracker = HaltTracker()
    event = make_event()
    list(tracker.ingest([event]))  # first sighting
    out = list(tracker.ingest([event]))  # second sighting (same event re-fetched)
    assert out == []


def test_resume_published_after_halt_emits_resume():
    tracker = HaltTracker()
    halt_only = make_event()
    list(tracker.ingest([halt_only]))

    halt_with_resume = make_event(resume_trade_time="07:30:00")
    out = list(tracker.ingest([halt_with_resume]))
    assert len(out) == 1
    assert out[0][0] == "resume"


def test_resume_only_emitted_once():
    tracker = HaltTracker()
    halt_only = make_event()
    list(tracker.ingest([halt_only]))
    halt_with_resume = make_event(resume_trade_time="07:30:00")
    list(tracker.ingest([halt_with_resume]))
    # Same event re-fetched again
    out = list(tracker.ingest([halt_with_resume]))
    assert out == []


def test_first_sighting_already_resumed_emits_both():
    """Edge case: feed roll-on shows a halt that already has resume time."""
    tracker = HaltTracker()
    event = make_event(resume_trade_time="07:30:00")
    out = list(tracker.ingest([event]))
    assert len(out) == 2
    assert out[0][0] == "halt"
    assert out[1][0] == "resume"


def test_cross_feed_dedup_by_halt_id():
    """Same halt event reported by both Nasdaq RSS and NYSE CSV → emit once."""
    tracker = HaltTracker()
    e_nasdaq = make_event(symbol="ARVN")
    e_nyse = HaltEvent(
        symbol="ARVN",
        exchange="NYSE",
        halt_date="2026-05-05",
        halt_time="06:55:32",  # same halt-id as e_nasdaq
        reason_code="T1",
        reason_description="News Pending",
        source="nyse_csv",
    )
    out = list(tracker.ingest([e_nasdaq, e_nyse]))
    assert len(out) == 1
    assert out[0][0] == "halt"


def test_different_halts_same_symbol_different_times():
    """Two halts on same ticker on different dates/times — both emit."""
    tracker = HaltTracker()
    e1 = make_event(date="2026-05-05", time="06:55:32")
    e2 = make_event(date="2026-05-06", time="10:00:00")
    out = list(tracker.ingest([e1, e2]))
    assert len(out) == 2
