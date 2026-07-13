"""Tests for halt + resume template rendering."""
from src.feeds.types import HaltEvent
from src.news.types import NewsItem
from src.template import render_followup, render_halt, render_resume


def make_news(**overrides):
    defaults = dict(
        source="prnewswire",
        title="Viridian reports positive Phase 3 topline results",
        body="b",
        url="https://prn.test/vrdn",
        published_at="2026-05-05T11:10:00+00:00",  # 07:10 ET
        tickers=("VRDN",),
    )
    defaults.update(overrides)
    return NewsItem(**defaults)


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


def test_render_halt_with_note_context_inserts_line_before_sector():
    event = make_event()
    out = render_halt(
        event, sector="MedTech", subsector="Med Devices",
        note_context="Note VRDN is scheduled to report earnings this morning",
    )
    lines = out.split("\n")
    note_idx = next(i for i, l in enumerate(lines) if l.startswith("Note "))
    sector_idx = next(i for i, l in enumerate(lines) if l.startswith("Sector:"))
    assert note_idx < sector_idx
    assert "Note VRDN is scheduled to report earnings this morning" in out


def test_render_halt_without_note_context_unchanged():
    event = make_event()
    base = render_halt(event, sector="MedTech")
    explicit_none = render_halt(event, sector="MedTech", note_context=None)
    assert base == explicit_none


def test_render_halt_biotech_includes_triage_cta():
    """Biotech halts carry the copy-pasteable triage nudge (option A, 2026-06-16)."""
    event = make_event()
    out = render_halt(event, sector="Biopharma", subsector="Biotech")
    assert "Biotech halt — triage this name?" in out
    assert "`triage VRDN`" in out


def test_render_halt_non_biotech_no_triage_cta():
    """Non-biotech halts must NOT carry the triage nudge."""
    event = make_event()
    out = render_halt(event, sector="MedTech", subsector="Diagnostics")
    assert "triage this name" not in out
    assert "triage VRDN" not in out


def test_render_followup_full_shape():
    """§7 header uses the news publish time in ET, references the halt in-body."""
    out = render_followup(
        make_event(halt_time="07:00:00"), make_news(),
        sector="Biopharma", subsector="Biotech",
    )
    lines = out.split("\n")
    assert lines[0] == (
        "07:10 ET 5/05/26 [StreetAccount] VRDN "
        "Follow-up: Viridian reports positive Phase 3 topline results ($14.06)"
    )
    assert "Follows the 07:00 ET halt on VRDN" in out
    assert "Sector: Biopharma / Biotech" in out
    assert "Source: PR Newswire press release" in out


def test_render_followup_uses_news_publish_time_not_halt_time():
    out = render_followup(
        make_event(halt_time="07:00:00"),
        make_news(published_at="2026-05-05T13:30:00+00:00"),  # 09:30 ET
    )
    assert out.startswith("09:30 ET 5/05/26 [StreetAccount] VRDN Follow-up:")


def test_render_followup_falls_back_to_halt_time_on_bad_publish():
    out = render_followup(
        make_event(halt_time="07:00:00"),
        make_news(published_at="not-a-timestamp"),
    )
    assert out.startswith("07:00 ET 5/05/26 [StreetAccount] VRDN Follow-up:")


def test_render_followup_omits_price_when_none():
    out = render_followup(make_event(last_price=None), make_news())
    assert "Follow-up: Viridian reports positive Phase 3 topline results" in out
    assert "($" not in out


def test_render_followup_last_price_override():
    out = render_followup(make_event(last_price=14.06), make_news(), last_price=15.50)
    assert "($15.50)" in out
    assert "($14.06)" not in out


def test_render_followup_truncates_long_headline():
    out = render_followup(make_event(), make_news(title="word " * 100))  # ~500 chars
    assert "…" in out
    header = out.split("\n")[0]
    assert len(header) < 260


def test_render_followup_globenewswire_label():
    out = render_followup(make_event(), make_news(source="globenewswire"))
    assert "Source: GlobeNewswire press release" in out


def test_render_followup_omits_sector_when_absent():
    out = render_followup(make_event(), make_news())
    assert "Sector:" not in out


def test_date_format_matches_sa_grammar():
    """SA bodies use M/DD/YY (single-digit month, 2-digit day, 2-digit year)."""
    event = make_event(halt_date="2026-05-05", halt_time="06:55:32")
    out = render_halt(event)
    assert "5/05/26" in out

    event2 = make_event(halt_date="2026-12-19")
    out2 = render_halt(event2)
    assert "12/19/26" in out2
