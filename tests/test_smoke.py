"""End-to-end smoke test of the halt-monitor without live feeds.

Builds synthetic events, runs them through the dedup tracker, renders
them via the template module, and confirms the output looks like the
sa-monitor halt template documented in template-library.md §3 and §6.
"""
from src.coverage import Universe
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent
from src.template import render_halt, render_resume


def test_synthetic_in_universe_halt_renders():
    universe = Universe()
    # Use IDXX since it's in the Phase 1 universe
    event = HaltEvent(
        symbol="IDXX",
        exchange="NASDAQ",
        halt_date="2026-05-05",
        halt_time="08:00:00",
        reason_code="T1",
        reason_description="News Pending",
        name="IDEXX Laboratories Inc",
        last_price=563.12,
        source="nasdaq_rss",
    )
    assert event.symbol in universe
    meta = universe.get(event.symbol)
    rendered = render_halt(
        event,
        sector=meta.sector,
        subsector=meta.subsector,
        name_override=meta.name,
    )
    assert "SA: IDXX" in rendered
    assert "halted at $563.12" in rendered
    assert "Sector: Healthcare Services" in rendered


def test_synthetic_resume_renders():
    universe = Universe()
    event = HaltEvent(
        symbol="IDXX",
        exchange="NASDAQ",
        halt_date="2026-05-05",
        halt_time="08:00:00",
        reason_code="T1",
        reason_description="News Pending",
        name="IDEXX Laboratories Inc",
        last_price=563.12,
        resume_trade_time="08:30:00",
        source="nasdaq_rss",
    )
    meta = universe.get(event.symbol)
    rendered = render_resume(
        event,
        sector=meta.sector,
        subsector=meta.subsector,
        name_override=meta.name,
    )
    assert "SA: IDXX [shares to resume trading at 08:30 ET]" in rendered
    assert "originally halted at 08:00 ET" in rendered


def test_halt_tracker_emits_halt_then_resume_for_full_cycle():
    """Simulate the full feed-poll cycle: halt event observed, then resume info added."""
    tracker = HaltTracker()
    halt_only = HaltEvent(
        symbol="ARVN",
        exchange="NASDAQ",
        halt_date="2026-05-01",
        halt_time="11:23:00",
        reason_code="T1",
        reason_description="News Pending",
        source="nasdaq_rss",
    )
    halt_with_resume = HaltEvent(
        symbol="ARVN",
        exchange="NASDAQ",
        halt_date="2026-05-01",
        halt_time="11:23:00",
        reason_code="T1",
        reason_description="News Pending",
        resume_trade_time="11:35:00",
        source="nasdaq_rss",
    )
    # First poll: just the halt
    out_first = list(tracker.ingest([halt_only]))
    assert [k for k, _ in out_first] == ["halt"]
    # Second poll: same halt re-fetched
    out_second = list(tracker.ingest([halt_only]))
    assert out_second == []
    # Third poll: resume info now populated
    out_third = list(tracker.ingest([halt_with_resume]))
    assert [k for k, _ in out_third] == ["resume"]
    # Fourth poll: still seeing the resumed event — no further emit
    out_fourth = list(tracker.ingest([halt_with_resume]))
    assert out_fourth == []
