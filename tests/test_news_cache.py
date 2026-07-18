"""Tests for the rolling news cache."""
from datetime import datetime, timedelta, timezone

from src.news.cache import NewsCache
from src.news.types import NewsItem


def _item(ticker, published_at, source="prnewswire", title="t", url=None):
    return NewsItem(
        source=source,
        title=title,
        body="body",
        url=url or f"https://x.test/{ticker}/{published_at}",
        published_at=published_at,
        tickers=(ticker,),
    )


def test_ingest_indexes_by_ticker():
    cache = NewsCache(window_minutes=60)
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    added = cache.ingest([_item("FOO", "2026-05-08T11:55:00+00:00")], now_utc=now)
    assert added == 1
    assert cache.tickers_indexed == 1
    matches = cache.lookup("FOO", now)
    assert len(matches) == 1
    assert matches[0].tickers == ("FOO",)


def test_ingest_dedups_by_news_id():
    cache = NewsCache(window_minutes=60)
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    item = _item("FOO", "2026-05-08T11:55:00+00:00")
    cache.ingest([item], now_utc=now)
    added2 = cache.ingest([item], now_utc=now)
    assert added2 == 0
    assert len(cache) == 1


def test_ingest_skips_items_without_tickers():
    cache = NewsCache()
    no_ticker_item = NewsItem(
        source="prnewswire", title="t", body="b",
        url="https://x.test/notickers", published_at="2026-05-08T11:55:00+00:00",
        tickers=(),
    )
    added = cache.ingest([no_ticker_item])
    assert added == 0
    assert len(cache) == 0


def test_ingest_evicts_aged_items():
    cache = NewsCache(window_minutes=30)
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cache.ingest([_item("FOO", "2026-05-08T11:00:00+00:00")], now_utc=now)
    # initial item is 60min old, window is 30min — should age out
    matches = cache.lookup("FOO", now)
    assert matches == []
    # cache empty now since the only ticker's items were all evicted
    assert cache.tickers_indexed == 0


def test_lookup_window_inclusive_and_lookforward():
    cache = NewsCache()
    halt = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cache.ingest([
        _item("FOO", "2026-05-08T11:30:00+00:00"),  # 30 min before — in window
        _item("FOO", "2026-05-08T12:03:00+00:00", url="https://x.test/2"),  # 3 min after — in lookforward
        _item("FOO", "2026-05-08T11:00:00+00:00", url="https://x.test/3"),  # 60 min before — boundary, in
        _item("FOO", "2026-05-08T10:59:00+00:00", url="https://x.test/4"),  # 61 min before — out
        _item("FOO", "2026-05-08T12:06:00+00:00", url="https://x.test/5"),  # 6 min after — out (>5)
    ], now_utc=halt)
    matches = cache.lookup("FOO", halt, lookback_minutes=60, lookforward_minutes=5)
    urls = [m.url for m in matches]
    assert "https://x.test/4" not in urls
    assert "https://x.test/5" not in urls
    assert "https://x.test/3" in urls
    assert "https://x.test/2" in urls


def test_lookup_returns_newest_first():
    cache = NewsCache()
    halt = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cache.ingest([
        _item("FOO", "2026-05-08T11:30:00+00:00", url="https://x.test/a"),
        _item("FOO", "2026-05-08T11:55:00+00:00", url="https://x.test/b"),
        _item("FOO", "2026-05-08T11:10:00+00:00", url="https://x.test/c"),
    ], now_utc=halt)
    matches = cache.lookup("FOO", halt)
    assert [m.url for m in matches] == [
        "https://x.test/b",
        "https://x.test/a",
        "https://x.test/c",
    ]


def test_lookup_case_insensitive_ticker():
    cache = NewsCache()
    halt = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cache.ingest([_item("FOO", "2026-05-08T11:55:00+00:00")], now_utc=halt)
    assert cache.lookup("foo", halt)
    assert cache.lookup("FOO", halt)


def test_lookup_no_match_for_unindexed_ticker():
    cache = NewsCache()
    halt = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    assert cache.lookup("ZZZZ", halt) == []


def test_multi_ticker_news_indexed_under_issuer_only():
    """A release that mentions multiple tickers resolves ONLY from its issuer
    (the first/subject ticker), never from a passing partner/rival mention —
    otherwise a halt on the mentioned name would falsely cross-ref this release."""
    cache = NewsCache()
    halt = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    multi = NewsItem(
        source="prnewswire", title="Foo comments on Bar approval", body="body",
        url="https://x.test/multi", published_at="2026-05-08T11:55:00+00:00",
        tickers=("FOO", "BAR"),  # FOO issues; BAR is a passing mention
    )
    cache.ingest([multi], now_utc=halt)
    assert cache.lookup("FOO", halt)          # issuer resolves
    assert cache.lookup("BAR", halt) == []    # passing mention does NOT
    assert cache.tickers_indexed == 1         # indexed under one ticker only
    assert len(cache) == 1                    # counted once in seen_ids
