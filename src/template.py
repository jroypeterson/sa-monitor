"""Render halt and resume events to the sa-monitor Slack/stdout template.

Template grammar lives in template-library.md §3 (basic halt) and §6 (resume).
We use a tightened sa-monitor variant — see those sections — that adds the
exchange-feed reason code (which SA does not surface) and the elapsed-halt
duration on resume (which we can compute from the feed timestamps).

For Phase 1 D4: this module returns plain text strings for stdout printing.
D5 will switch to Slack Block Kit per HEALTH_REPORTING.md §4.1 conventions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .feeds.types import HaltEvent
from .news.types import NewsItem

_ET = ZoneInfo("America/New_York")

# Presentation labels for news-wire sources. Mirrors enrichment._NEWS_SOURCE_LABELS
# (kept local so template.py has no upward dependency on enrichment).
_NEWS_SOURCE_LABELS = {
    "prnewswire": "PR Newswire",
    "businesswire": "Business Wire",
    "globenewswire": "GlobeNewswire",
}

# Cap for the {headline} portion of a §7 Follow-up. SA follow-up subjects run
# long; this keeps the Slack line readable while preserving the substance.
_FOLLOWUP_HEADLINE_LIMIT = 200


def _format_date_short(iso_date: str) -> str:
    """ '2026-05-05' -> '5/05/26' (matches SA's body grammar). """
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return f"{dt.month}/{dt.day:02d}/{dt.year % 100:02d}"
    except (ValueError, TypeError):
        return iso_date


def _format_time_hhmm(time_str: str) -> str:
    """ '06:56:32' -> '06:56'. Resume notifications use HH:MM in SA's grammar. """
    if not time_str:
        return ""
    parts = time_str.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return time_str


def _format_price(price: Optional[float]) -> str:
    """Format price as '$X.XX' or empty if None."""
    if price is None:
        return ""
    return f"${price:.2f}"


def _ticker_display_name(event: HaltEvent, name_override: str = "") -> str:
    """Prefer name from sa_monitor_universe.json (override) over feed name."""
    return (name_override or event.name or event.symbol).strip()


def is_biotech(subsector: str) -> bool:
    """True when the name's CM subsector is Biotech (case/space-insensitive)."""
    return (subsector or "").strip().casefold() == "biotech"


def biotech_triage_cta(symbol: str) -> str:
    """Lean halt->triage hand-off nudge for a biotech halt (option A, 2026-06-16).

    sa-monitor can't auto-invoke the Claude-driven biotech_triage, so instead of
    pretending to trigger it we surface a copy-pasteable command. See the root
    biotech_catalyst_architecture_plan.md (§3) for why this is human-mediated.
    """
    return f":dna: Biotech halt — triage this name?  ->  `triage {symbol}`"


def render_halt(event: HaltEvent, *, sector: str = "", subsector: str = "",
                name_override: str = "", note_context: Optional[str] = None) -> str:
    """Render a halt notification — sa-monitor variant.

    Phase 1 v0 template (per template-library.md §3):

        SA: TICKER [Company halted, news pending]
        HH:MM ET M/DD/YY [TICKER] halted at $X.XX, reason code [CODE - description]
        Note TICKER is scheduled to report earnings this morning   <-- Phase 2 enrichment
        Sector: {sector} / {subsector}
    """
    name = _ticker_display_name(event, name_override)
    date_short = _format_date_short(event.halt_date)
    time_hhmm = _format_time_hhmm(event.halt_time)
    price_str = _format_price(event.last_price)

    headline = f"SA: {event.symbol} [{name} halted, news pending]"

    code_block = f"[{event.reason_code} - {event.reason_description}]"

    if price_str:
        body_line = (
            f"{time_hhmm} ET {date_short} [{event.symbol}] halted at {price_str}, "
            f"reason code {code_block}"
        )
    else:
        body_line = (
            f"{time_hhmm} ET {date_short} [{event.symbol}] halted, reason code "
            f"{code_block}"
        )

    sector_line = ""
    if sector:
        sector_line = f"Sector: {sector}"
        if subsector:
            sector_line += f" / {subsector}"

    parts = [headline, body_line]
    if note_context:
        parts.append(note_context)
    if sector_line:
        parts.append(sector_line)
    if is_biotech(subsector):
        parts.append(biotech_triage_cta(event.symbol))
    parts.append(f"Source: {event.source} ({event.exchange})")
    return "\n".join(parts)


def _iso_utc_to_et(iso_ts: str) -> Optional[datetime]:
    """ISO-8601 UTC timestamp -> ET datetime; None on malformed input."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET)


def followup_when(halt: HaltEvent, item: NewsItem) -> tuple[str, str]:
    """(time_hhmm, date_short) for a §7 Follow-up header.

    The follow-up crosses when the news breaks, so the header stamps the news
    item's publish time in ET. Falls back to the halt's own timestamp if the
    item has no parseable publish time. Shared by render_followup + Slack so
    both render the identical header.
    """
    et = _iso_utc_to_et(item.published_at)
    if et is not None:
        return (f"{et.hour:02d}:{et.minute:02d}",
                f"{et.month}/{et.day:02d}/{et.year % 100:02d}")
    return (_format_time_hhmm(halt.halt_time), _format_date_short(halt.halt_date))


def followup_headline(item: NewsItem) -> str:
    """The substantive headline for a §7 Follow-up, capped for readability."""
    headline = (item.title or "").strip()
    if len(headline) > _FOLLOWUP_HEADLINE_LIMIT:
        headline = headline[:_FOLLOWUP_HEADLINE_LIMIT].rsplit(" ", 1)[0] + "…"
    return headline


def followup_source_label(item: NewsItem) -> str:
    """Pretty wire-source label (e.g. 'PR Newswire') for a §7 Follow-up."""
    return _NEWS_SOURCE_LABELS.get(item.source, item.source)


def render_followup(halt: HaltEvent, item: NewsItem, *, sector: str = "",
                    subsector: str = "", last_price: Optional[float] = None) -> str:
    """Render a §7 Follow-up alert — the substantive news that broke on a
    previously-halted covered name (template-library.md §7, webhook variant).

        HH:MM ET M/DD/YY [StreetAccount] TICKER Follow-up: {headline} ($X.XX)
        Follows the HH:MM ET halt on TICKER
        Sector: {sector} / {subsector}
        Source: {Wire} press release

    sa-monitor posts via webhook (no Slack threading), so the original halt is
    referenced in-body rather than via SA's archive block. Price is the halt's
    last_price unless a fresher one is supplied.
    """
    symbol = halt.symbol
    time_hhmm, date_short = followup_when(halt, item)
    headline = followup_headline(item)

    price = last_price if last_price is not None else halt.last_price
    price_str = _format_price(price)

    header = (
        f"{time_hhmm} ET {date_short} [StreetAccount] {symbol} "
        f"Follow-up: {headline}"
    )
    if price_str:
        header += f" ({price_str})"

    halt_hhmm = _format_time_hhmm(halt.halt_time)
    back_ref = f"Follows the {halt_hhmm} ET halt on {symbol}"

    parts = [header, back_ref]
    if sector:
        sector_line = f"Sector: {sector}"
        if subsector:
            sector_line += f" / {subsector}"
        parts.append(sector_line)
    parts.append(f"Source: {followup_source_label(item)} press release")
    return "\n".join(parts)


def render_resume(event: HaltEvent, *, sector: str = "", subsector: str = "",
                  name_override: str = "") -> str:
    """Render a resume notification — sa-monitor variant.

    Phase 1 v0 template (per template-library.md §6):

        SA: TICKER [shares to resume trading at HH:MM ET]
        HH:MM ET M/DD/YY [TICKER] resume scheduled at HH:MM ET, originally halted at HH:MM ET
        Sector: {sector} / {subsector}

    Halt duration is omitted in v0 — it's computed in D6 with full timestamp
    parsing once we know how the exchange feeds publish resume timestamps.
    """
    name = _ticker_display_name(event, name_override)
    date_short = _format_date_short(event.halt_date)
    halt_time_hhmm = _format_time_hhmm(event.halt_time)
    resume_time_hhmm = _format_time_hhmm(event.resume_trade_time or "")

    headline = f"SA: {event.symbol} [shares to resume trading at {resume_time_hhmm} ET]"

    body_line = (
        f"{resume_time_hhmm} ET {date_short} [{event.symbol}] resume scheduled "
        f"at {resume_time_hhmm} ET, originally halted at {halt_time_hhmm} ET "
        f"({event.reason_code} - {event.reason_description})"
    )

    sector_line = ""
    if sector:
        sector_line = f"Sector: {sector}"
        if subsector:
            sector_line += f" / {subsector}"

    parts = [headline, body_line]
    if sector_line:
        parts.append(sector_line)
    parts.append(f"Source: {event.source} ({event.exchange})")
    return "\n".join(parts)
