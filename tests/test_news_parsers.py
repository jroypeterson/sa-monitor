"""Tests for shared news-wire parsing utilities."""
from src.news.parsers import extract_tickers, parse_pubdate, strip_html, strip_ns


def test_strip_html_removes_tags_and_collapses_whitespace():
    assert strip_html("<p>Hello   <b>world</b></p>") == "Hello world"


def test_strip_html_decodes_entities():
    assert strip_html("Q&amp;A &mdash; today") == "Q&A — today"


def test_strip_html_handles_empty():
    assert strip_html("") == ""
    assert strip_html(None) == ""  # type: ignore[arg-type]


def test_parse_pubdate_rfc822_to_iso_utc():
    iso = parse_pubdate("Fri, 8 May 2026 00:30:00 +0000")
    assert iso == "2026-05-08T00:30:00+00:00"


def test_parse_pubdate_with_offset_normalizes_to_utc():
    iso = parse_pubdate("Thu, 7 May 2026 20:30:00 -0400")
    # 20:30 -0400 == 00:30 UTC next day
    assert iso == "2026-05-08T00:30:00+00:00"


def test_parse_pubdate_naive_treated_as_utc():
    iso = parse_pubdate("Fri, 8 May 2026 00:30:00")
    assert iso == "2026-05-08T00:30:00+00:00"


def test_parse_pubdate_malformed_returns_none():
    assert parse_pubdate("not a date") is None
    assert parse_pubdate("") is None


def test_extract_tickers_nasdaq_basic():
    assert extract_tickers("PDF Solutions, Inc. (Nasdaq: PDFS), a leading provider") == ("PDFS",)


def test_extract_tickers_nyse():
    assert extract_tickers("Pfizer (NYSE: PFE) announced today") == ("PFE",)


def test_extract_tickers_share_class_dotted():
    assert extract_tickers("Berkshire (NYSE: BRK.A) reported") == ("BRK.A",)


def test_extract_tickers_nyse_american_with_space():
    assert extract_tickers("Acme Corp (NYSE American: ACME) said") == ("ACME",)


def test_extract_tickers_multiple_unique_first_seen_order():
    text = "Trial sponsored by Foo (NASDAQ: FOO) with partner Bar (NYSE: BAR). Also (NASDAQ: FOO) again."
    assert extract_tickers(text) == ("FOO", "BAR")


def test_extract_tickers_otc_codes():
    assert extract_tickers("(OTCQX: ABCD)") == ("ABCD",)
    assert extract_tickers("(OTCQB: WXYZ)") == ("WXYZ",)


def test_extract_tickers_canadian_codes():
    assert extract_tickers("(TSX: SHOP) (TSXV: TINY) (NEO: ABC) (CSE: XYZ)") == ("SHOP", "TINY", "ABC", "XYZ")


def test_extract_tickers_no_match_lowercase_or_prose():
    # Lowercase prose shouldn't match — exchange prefix is required + capitalized
    assert extract_tickers("nasdaq composite was up today") == ()
    # Exchange prefix without colon shouldn't match
    assert extract_tickers("listed on NASDAQ ABCD") == ()


def test_extract_tickers_skips_nontickers_after_colon():
    # Defensive: something like "(NYSE: see story below)" shouldn't match
    # because "see" lowercases on first char
    assert extract_tickers("(NYSE: see story below)") == ()


def test_extract_tickers_caps_length_at_8_chars():
    # Tickers longer than 8 chars are filtered (defensive — real tickers
    # max out at ~5 letters + class suffix, never 9+)
    assert extract_tickers("(NASDAQ: NINECHARS)") == ()


def test_strip_ns_strips_namespace():
    assert strip_ns("{http://www.nasdaqtrader.com/}IssueSymbol") == "IssueSymbol"
    assert strip_ns("simple") == "simple"
