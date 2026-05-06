"""Tests for halt + resume template rendering."""
from src.feeds.types import HaltEvent
from src.template import render_halt, render_resume


def make_event(**overrides):
    defaults = dict(
        symbol="VRDN",
        exchange="Nasdaq",
        halt_date="2026-05-05",
        halt_time="06:55:32",
        reason_code="T1",
        reason_description="News Pending",
        name="Viridian Therapeutics",
        last_price=14.06,
        source="nasdaq_rss",
    )
    defaults.update(overrides)
    return HaltEvent(**defaults)


def test_render_halt_basic_with_price():
    event = make_event()
    out = render_halt(event, sector="MedTech", subsector="Diagnostics")
    assert "SA: VRDN [Viridian Therapeutics halted, news pending]" in out
    assert "06:55 ET 5/05/26 [VRDN] halted at $14.06" in out
    assert "[T1 - News Pending]" in out
    assert "Sector: MedTech / Diagnostics" in out
    assert "Source: nasdaq_rss (Nasdaq)" in out


def test_render_halt_no_price():
    event = make_event(last_price=None)
    out = render_halt(event)
    assert "halted at" not in out  # no price, no "halted at"
    assert "halted, reason code" in out


def test_render_halt_no_subsector():
    event = make_event()
    out = render_halt(event, sector="Tech")
    assert "Sector: Tech" in out
    assert "Sector: Tech /" not in out


def test_render_halt_no_sector():
    event = make_event()
    out = render_halt(event)
    assert "Sector:" not in out


def test_render_halt_uses_name_override():
    event = make_event(name="VRDN raw name from feed")
    out = render_halt(event, name_override="Viridian Therapeutics Inc")
    assert "Viridian Therapeutics Inc halted" in out
    assert "VRDN raw name" not in out


def test_render_resume_basic():
    event = make_event(resume_trade_time="07:30:00")
    out = render_resume(event, sector="MedTech", subsector="Diagnostics")
    assert "SA: VRDN [shares to resume trading at 07:30 ET]" in out
    assert "originally halted at 06:55 ET" in out
    assert "(T1 - News Pending)" in out
    assert "Sector: MedTech / Diagnostics" in out


def test_render_resume_handles_missing_resume_time():
    """If resume_trade_time is None somehow, render shouldn't crash."""
    event = make_event(resume_trade_time=None)
    out = render_resume(event)
    # No assertion on content — just confirm it doesn't raise
    assert "VRDN" in out


def test_date_format_matches_sa_grammar():
    """SA bodies use M/DD/YY (single-digit month, 2-digit day, 2-digit year)."""
    event = make_event(halt_date="2026-05-05", halt_time="06:55:32")
    out = render_halt(event)
    assert "5/05/26" in out

    event2 = make_event(halt_date="2026-12-19")
    out2 = render_halt(event2)
    assert "12/19/26" in out2
