"""Tests for PR Newswire / Business Wire / GlobeNewswire RSS adapters.

Uses real-RSS samples captured 2026-05-08 in tests/fixtures/news/. These
samples mirror real production payload shapes — if a feed publisher changes
their schema, regenerate the fixture (curl the source URL to a file) and
update assertions.
"""
from pathlib import Path

import pytest

from src.news import bw, gnw, prnewswire as prn
from src.news.types import NewsItem


FIXTURES = Path(__file__).parent / "fixtures" / "news"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ----- PRN -----

def test_prn_parses_real_sample():
    items = prn.parse(_read("prn_health_sample.xml"))
    assert len(items) >= 10  # PRN healthcare typically returns ~20
    assert all(isinstance(i, NewsItem) for i in items)
    assert all(i.source == "prnewswire" for i in items)


def test_prn_first_item_has_required_fields():
    items = prn.parse(_read("prn_health_sample.xml"))
    first = items[0]
    assert first.title
    assert first.url.startswith("http")
    assert first.body
    # PRN dates are ISO with TZ offset, not naive
    assert "T" in first.published_at and (
        first.published_at.endswith("+00:00") or "+" in first.published_at[10:]
    )


def test_prn_surfaces_industry_taxonomy():
    items = prn.parse(_read("prn_health_sample.xml"))
    # PRN healthcare items always carry industry tags like 'Biotechnology',
    # 'Pharmaceuticals', etc.
    has_taxonomy = [i for i in items if i.industries]
    assert len(has_taxonomy) >= 5, "expected most PRN health items to carry industry tags"


def test_prn_skips_items_missing_title_or_link():
    """Synthetic missing-field item should be silently dropped."""
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Has title and link</title><link>https://x.test/a</link>
            <description>body</description><pubDate>Fri, 8 May 2026 00:00:00 +0000</pubDate>
      </item>
      <item><title>No link, dropped</title><description>body</description></item>
      <item><link>https://x.test/c</link><description>No title, dropped</description></item>
    </channel></rss>"""
    items = prn.parse(xml)
    assert len(items) == 1
    assert items[0].url == "https://x.test/a"


def test_prn_handles_malformed_xml_gracefully():
    items = prn.parse(b"not xml at all <<<")
    assert items == []


# ----- BW -----

def test_bw_parses_real_sample():
    items = bw.parse(_read("bw_sample.xml"))
    assert len(items) >= 10
    assert all(isinstance(i, NewsItem) for i in items)
    assert all(i.source == "businesswire" for i in items)


def test_bw_first_item_has_required_fields():
    items = bw.parse(_read("bw_sample.xml"))
    first = items[0]
    assert first.title
    assert first.url.startswith("http")
    assert first.published_at


def test_bw_industries_empty_by_design():
    """BW RSS doesn't expose taxonomy on items — industries should be empty."""
    items = bw.parse(_read("bw_sample.xml"))
    assert all(i.industries == () for i in items)


# ----- GNW -----

def test_gnw_parses_real_sample():
    items = gnw.parse(_read("gnw_health_sample.xml"))
    assert len(items) >= 10
    assert all(isinstance(i, NewsItem) for i in items)
    assert all(i.source == "globenewswire" for i in items)


def test_gnw_first_item_has_required_fields():
    items = gnw.parse(_read("gnw_health_sample.xml"))
    first = items[0]
    assert first.title
    assert first.url.startswith("http")
    assert first.published_at


def test_gnw_extracts_tickers_from_body():
    """GNW items often contain '(Nasdaq: ABCD)' in body — verify extraction
    works through the parser pipeline."""
    items = gnw.parse(_read("gnw_health_sample.xml"))
    with_tickers = [i for i in items if i.tickers]
    # Real-sample expectation: at least a few items mention a ticker prefix
    assert len(with_tickers) >= 2, (
        f"expected ≥2 items with ticker mentions; got {len(with_tickers)}: "
        f"{[(i.title[:40], i.tickers) for i in items[:5]]}"
    )


def test_gnw_surfaces_category_or_subject_taxonomy():
    """GNW exposes <category> + <subject> tags."""
    items = gnw.parse(_read("gnw_health_sample.xml"))
    with_industries = [i for i in items if i.industries]
    assert len(with_industries) >= 1
