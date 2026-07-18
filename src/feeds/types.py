"""Shared types for halt-feed parsers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


class FeedParseError(RuntimeError):
    """A feed returned a 200 whose body is NOT the expected feed shape.

    Raised by the fetch() layer (nasdaq.fetch / nyse.fetch) when a soft failure
    slips through HTTP status — an HTML error page, a WAF/CDN challenge, a
    truncated body — that would otherwise parse() to an empty list and be
    indistinguishable from a genuine "no halts right now". Kept strictly at the
    fetch() layer: parse() tolerance is a pinned invariant, so the shape check
    lives in fetch(), not parse().
    """


def _canonical_time(t: str) -> str:
    """Normalize a halt time to zero-padded 'HH:MM:SS' for the dedup id.

    Different feeds format the same instant differently (Nasdaq RSS may emit
    '6:55:32' where the NYSE CSV emits '06:55:32'); without canonicalization the
    halt_id tuple differs and the same halt double-alerts. Best-effort: if the
    string doesn't look like a time it's returned stripped, unchanged (parsers
    stay tolerant of odd inputs; display still uses the raw halt_time field).
    """
    s = (t or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})", s)
    if m:
        hh, mm, ss = m.groups()
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    return s


@dataclass(frozen=True)
class HaltEvent:
    """One halt event — same shape regardless of source feed.

    Halt ID (for dedup): (symbol, halt_date, halt_time). Two halts on the same
    symbol at the same exact second are pathological enough that we treat the
    tuple as primary-key.
    """

    symbol: str
    exchange: str  # "Nasdaq" | "NYSE" | "NYSE American" | "NYSE Arca" | etc.
    halt_date: str  # ISO date "YYYY-MM-DD" in ET
    halt_time: str  # "HH:MM:SS" in ET
    reason_code: str  # canonical Nasdaq code (T1, LUDP, …)
    reason_description: str  # human-readable
    name: str = ""  # company name as published by the feed
    last_price: Optional[float] = None  # may be None if feed doesn't include
    resume_date: Optional[str] = None  # set when resume is published
    resume_quote_time: Optional[str] = None
    resume_trade_time: Optional[str] = None
    source: str = ""  # "nasdaq_rss" | "nyse_csv"
    raw: dict = field(default_factory=dict)  # full source row for debug

    @property
    def halt_id(self) -> tuple[str, str, str]:
        """Dedup key — stable across re-fetches of the same event.

        Time is canonicalized to zero-padded 'HH:MM:SS' so a formatting
        difference between feeds ('6:55:32' vs '06:55:32') can't split one halt
        into two ids and double-alert.
        """
        return (self.symbol.upper(), self.halt_date, _canonical_time(self.halt_time))

    @property
    def is_resumed(self) -> bool:
        return self.resume_trade_time is not None

    def __str__(self) -> str:
        return f"{self.symbol} halt {self.halt_date} {self.halt_time} {self.reason_code} ({self.exchange})"
