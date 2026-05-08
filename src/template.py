"""Render halt and resume events to the sa-monitor Slack/stdout template.

Template grammar lives in template-library.md §3 (basic halt) and §6 (resume).
We use a tightened sa-monitor variant — see those sections — that adds the
exchange-feed reason code (which SA does not surface) and the elapsed-halt
duration on resume (which we can compute from the feed timestamps).

For Phase 1 D4: this module returns plain text strings for stdout printing.
D5 will switch to Slack Block Kit per HEALTH_REPORTING.md §4.1 conventions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .feeds.types import HaltEvent


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
    parts.append(f"Source: {event.source} ({event.exchange})")
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
