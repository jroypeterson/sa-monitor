"""Halt-event enrichment — the "Note:" context line on halt alerts (Phase 2).

Per template-library.md §4, SA halts often carry a one-line context preface like:
    Note ITGR is scheduled to report earnings this morning
    Note NKTR is holding a call today at 8:00ET to discuss topline results...
    Note RYTM ... PDUFA goal date for Imcivree sNDA is tomorrow

Phase 2 first cut covers the two context types we have published calendars for:
- earnings (from earnings-agent's exports/upcoming_events.json)
- analyst/investor/R&D/capital-markets days + tracked conferences (from analyst-days)

PDUFA + clinical-readout context is deferred to a later slice.

The rule of thumb is *only enrich when the calendar event is plausibly the
trigger for the halt* — same-day match. Cross-day enrichment (e.g. a halt
the day before an investor day) is not produced; the user can see the next
calendar event via other channels.
"""
from __future__ import annotations

from typing import Optional

from .calendars import AnalystDayCalendar, AnalystDayEvent, EarningsCalendar, EarningsEvent
from .feeds.types import HaltEvent


# Each entry is the full noun phrase including the article — "R&D" is read
# "ar-en-dee" so it takes "an" despite starting with the consonant "R", which
# rules me out of using a simple first-letter vowel test.
_ANALYST_DAY_PHRASES = {
    "investor_day": "an investor day",
    "analyst_day": "an analyst day",
    "rd_day": "an R&D day",
    "capital_markets_day": "a capital markets day",
}


def build_note_context(
    event: HaltEvent,
    *,
    earnings: Optional[EarningsCalendar] = None,
    analyst_days: Optional[AnalystDayCalendar] = None,
) -> Optional[str]:
    """Return the Note context string for a halt, or None if no enrichment applies.

    Tries earnings first (higher signal), then analyst-day events. Returns the
    first match — we don't compose multi-context Notes in Phase 2 first cut.
    """
    if earnings is not None:
        ev = earnings.get(event.symbol, event.halt_date)
        if ev is not None:
            return _earnings_note(event, ev)

    if analyst_days is not None:
        ad = analyst_days.get(event.symbol, event.halt_date)
        if ad is not None:
            note = _analyst_day_note(event, ad)
            if note is not None:
                return note

    return None


def _earnings_note(halt: HaltEvent, ev: EarningsEvent) -> str:
    when = _time_of_day_phrase(halt.halt_time, ev.event_hour)
    return f"Note {halt.symbol} is scheduled to report earnings {when}"


def _analyst_day_note(halt: HaltEvent, ev: AnalystDayEvent) -> Optional[str]:
    if ev.event_type == "conference":
        return f"Note {halt.symbol} is presenting at an investor conference today"
    phrase = _ANALYST_DAY_PHRASES.get(ev.event_type)
    if not phrase:
        return None
    return f"Note {halt.symbol} is hosting {phrase} today"


def _time_of_day_phrase(halt_time: str, event_hour: str) -> str:
    """Choose 'this morning' / 'this afternoon' / 'today' for the earnings Note.

    Prefer the explicit event_hour from earnings-agent (bmo|amc) — that reflects
    SA's own grammar choice. Fall back to the halt's wall-clock hour.
    """
    if event_hour == "bmo":
        return "this morning"
    if event_hour == "amc":
        return "this afternoon"
    try:
        hh = int(halt_time.split(":", 1)[0])
        return "this morning" if hh < 12 else "this afternoon"
    except (ValueError, IndexError):
        return "today"
