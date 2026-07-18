"""Rolling in-memory cache of news items for halt cross-reference.

Each session starts with an empty cache; first news poll populates it. Items
are indexed by the issuing company's ticker only (the first exchange-prefixed
mention — see NewsItem.issuer_ticker). Indexing under a merely-mentioned
partner/rival ticker would let a halt on that name falsely cross-ref/resolve
against a release it does not issue. The cache evicts items older than
`window_minutes` (default 60) on every
ingest — items that age out can no longer cross-ref a halt because by then
they're outside SA's typical lookback grammar.

Not persisted across sessions: cross-ref is most valuable for halts within
~60 min of the news, and the AM/PM session boundary is well outside that
window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .types import NewsItem


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class NewsCache:
    """In-memory rolling cache of NewsItems indexed by ticker.

    Thread-safety: not thread-safe. The halt_monitor poll loop is single-
    threaded so this is fine.
    """

    window_minutes: int = 60
    _by_ticker: dict[str, list[NewsItem]] = field(default_factory=dict)
    _seen_ids: set[str] = field(default_factory=set)

    def ingest(self, items: list[NewsItem], *, now_utc: Optional[datetime] = None) -> int:
        """Add new items to the cache, dedup by news_id, evict aged items.
        Returns the count of newly-added items (excludes dupes)."""
        now = now_utc or datetime.now(timezone.utc)
        added = 0
        for item in items:
            issuer = item.issuer_ticker
            if not issuer:
                continue
            if item.news_id in self._seen_ids:
                continue
            self._seen_ids.add(item.news_id)
            # Index under the ISSUER only, never every mentioned ticker — a
            # passing partner/rival mention must not resolve another name's halt.
            self._by_ticker.setdefault(issuer.upper(), []).append(item)
            added += 1
        self._evict_older_than(now - timedelta(minutes=self.window_minutes))
        return added

    def _evict_older_than(self, cutoff: datetime) -> None:
        for ticker, lst in list(self._by_ticker.items()):
            kept = [it for it in lst if (_parse_iso(it.published_at) or cutoff) >= cutoff]
            if kept:
                self._by_ticker[ticker] = kept
            else:
                del self._by_ticker[ticker]

    def lookup(self, ticker: str, halt_dt_utc: datetime,
               *, lookback_minutes: int = 60,
               lookforward_minutes: int = 5) -> list[NewsItem]:
        """Return news items for a ticker published within
        [halt_dt - lookback, halt_dt + lookforward]. Sorted newest-first.

        Lookforward is small (5 min) and exists to catch press releases that
        cross the wire seconds AFTER a halt fires — common pattern when
        a company files a halt request and issues PR concurrently.
        """
        items = self._by_ticker.get(ticker.upper(), [])
        if not items:
            return []
        lo = halt_dt_utc - timedelta(minutes=lookback_minutes)
        hi = halt_dt_utc + timedelta(minutes=lookforward_minutes)
        matches: list[tuple[datetime, NewsItem]] = []
        for it in items:
            pub = _parse_iso(it.published_at)
            if pub is None:
                continue
            if lo <= pub <= hi:
                matches.append((pub, it))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches]

    def __len__(self) -> int:
        return len(self._seen_ids)

    @property
    def tickers_indexed(self) -> int:
        return len(self._by_ticker)
