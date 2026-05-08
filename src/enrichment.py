"""Halt-event enrichment — the "Note:" context line on halt alerts (Phase 2).

Per template-library.md §4–§5, SA halts often carry a one-line context preface:

Slice 1 ("Note:" calendar context — LIVE):
    Note ITGR is scheduled to report earnings this morning
    Note AFRM is hosting an investor day today
    Note WST is presenting at an investor conference today

Slice 2B ("Follows {source} report that..." cross-ref — LIVE):
    Follows PR Newswire press release that {title}
    Follows Business Wire press release that {title}

Cross-ref takes priority over calendar context — a coincident wire press
release is a more specific signal than a generic "earnings today" note.

PDUFA + clinical-readout context is deferred to a later slice. Pure-
journalism feeds (FT/Bloomberg/Sky) are paywalled and out of scope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .calendars import AnalystDayCalendar, AnalystDayEvent, EarningsCalendar, EarningsEvent
from .feeds.types import HaltEvent
from .news.cache import NewsCache
from .news.types import NewsItem


# Each entry is the full noun phrase including the article — "R&D" is read
# "ar-en-dee" so it takes "an" despite starting with the consonant "R", which
# rules me out of using a simple first-letter vowel test.
_ANALYST_DAY_PHRASES = {
    "investor_day": "an investor day",
    "analyst_day": "an analyst day",
    "rd_day": "an R&D day",
    "capital_markets_day": "a capital markets day",
}

_NEWS_SOURCE_LABELS = {
    "prnewswire": "PR Newswire",
    "businesswire": "Business Wire",
    "globenewswire": "GlobeNewswire",
}

# Cap for the {title} portion of cross-ref notes. Real SA bodies typically
# inline ~80-120 chars before "(see linked comment)". We don't render the
# linked comment, so a slightly tighter cap keeps Slack lines readable.
_CROSS_REF_TITLE_LIMIT = 140


def build_note_context(
    event: HaltEvent,
    *,
    earnings: Optional[EarningsCalendar] = None,
    analyst_days: Optional[AnalystDayCalendar] = None,
    news_cache: Optional[NewsCache] = None,
) -> Optional[str]:
    """Return the Note context string for a halt, or None if no enrichment applies.

    Priority order:
    1. News cross-ref (most specific — actual press release coincident with halt)
    2. Earnings calendar (same-day match, AMC/BMO grammar)
    3. Analyst-day calendar (same-day match)
    """
    if news_cache is not None:
        cross_ref = _cross_ref_note(event, news_cache)
        if cross_ref is not None:
            return cross_ref

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


def _cross_ref_note(halt: HaltEvent, cache: NewsCache) -> Optional[str]:
    """Look up news items in the cache that match this halt by ticker + time.
    If a match exists, render a 'Follows {source} press release that {title}' note."""
    halt_dt_utc = _halt_dt_to_utc(halt)
    if halt_dt_utc is None:
        return None
    matches = cache.lookup(halt.symbol, halt_dt_utc)
    if not matches:
        return None
    item = matches[0]  # newest within the window
    label = _NEWS_SOURCE_LABELS.get(item.source, item.source)
    title = (item.title or "").strip()
    if len(title) > _CROSS_REF_TITLE_LIMIT:
        title = title[:_CROSS_REF_TITLE_LIMIT].rsplit(" ", 1)[0] + "…"
    return f"Follows {label} press release: {title}"


def _halt_dt_to_utc(halt: HaltEvent) -> Optional[datetime]:
    """Convert halt_date + halt_time (in ET) to a UTC datetime.

    Halt feeds publish wall-clock ET time; converting to UTC requires DST
    awareness. Use zoneinfo's America/New_York which handles EDT/EST splits
    correctly. Returns None on malformed input rather than raising.
    """
    if not halt.halt_date or not halt.halt_time:
        return None
    parts = halt.halt_time.split(":")
    if len(parts) < 2:
        return None
    try:
        y, m, d = (int(x) for x in halt.halt_date.split("-"))
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(float(parts[2])) if len(parts) >= 3 else 0
    except (ValueError, IndexError):
        return None
    et = ZoneInfo("America/New_York")
    try:
        local = datetime(y, m, d, hh, mm, ss, tzinfo=et)
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


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
