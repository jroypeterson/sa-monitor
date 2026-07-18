"""Shared types for news-wire parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NewsItem:
    """One news-wire item — same shape regardless of source.

    Dedup key: `url` (the RSS guid is typically the URL itself).
    """

    source: str            # 'prnewswire' | 'businesswire' | 'globenewswire'
    title: str
    body: str              # plain text, HTML stripped, entities decoded
    url: str
    published_at: str      # ISO 8601 UTC, e.g. '2026-05-08T00:30:00+00:00'
    tickers: tuple[str, ...] = ()  # extracted from body via regex
    industries: tuple[str, ...] = ()  # source-specific taxonomy tags
    raw: dict = field(default_factory=dict)

    @property
    def news_id(self) -> str:
        """Stable dedup key — same item across re-fetches resolves to one ID."""
        return self.url

    @property
    def issuer_ticker(self) -> Optional[str]:
        """The subject/issuer of this release — the FIRST exchange-prefixed
        ticker (dateline/lead convention), or None if none were extracted.

        Attribution must use this, NOT any ticker in `tickers`: a PR-wire body
        often name-drops a partner/rival/read-across ticker
        (`Acme (NASDAQ: ACME) comments on FDA approval of RivalCorp (NASDAQ: VRDN)`).
        Treating every mention as the issuer mis-attributes cross-ref/follow-up
        and HC-event alerts to the wrong (merely-mentioned) covered name. The
        issuer's own ticker leads on these wires, so first-seen = subject.
        """
        return self.tickers[0] if self.tickers else None

    def __str__(self) -> str:
        tickers_str = f" tickers={','.join(self.tickers)}" if self.tickers else ""
        return f"{self.source}: {self.title[:80]}{tickers_str} ({self.published_at})"
