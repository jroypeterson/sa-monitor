"""Shared types for halt-feed parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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
        """Dedup key — stable across re-fetches of the same event."""
        return (self.symbol.upper(), self.halt_date, self.halt_time)

    @property
    def is_resumed(self) -> bool:
        return self.resume_trade_time is not None

    def __str__(self) -> str:
        return f"{self.symbol} halt {self.halt_date} {self.halt_time} {self.reason_code} ({self.exchange})"
