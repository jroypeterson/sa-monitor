"""Tests for Nasdaq RSS + NYSE CSV parsers using fixture data."""
from pathlib import Path
from unittest.mock import patch

import pytest

from src.feeds import nasdaq, nyse
from src.feeds.types import FeedParseError, HaltEvent

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeResp:
    """Minimal requests.Response stand-in for fetch()-layer tests."""

    def __init__(self, *, content=b"", text="", status=200):
        self.content = content
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        return None  # soft failures return HTTP 200 — status never trips


def test_nasdaq_parse_basic_halt():
    xml = (FIXTURES / "nasdaq_rss_sample.xml").read_bytes()
    events = nasdaq.parse(xml)
    assert len(events) == 3

    vrdn = events[0]
    assert vrdn.symbol == "VRDN"
    assert vrdn.exchange == "NASDAQ"
    assert vrdn.halt_date == "2026-05-05"
    assert vrdn.halt_time == "06:55:32"
    assert vrdn.reason_code == "T1"
    assert vrdn.reason_description == "News Pending"
    assert vrdn.name == "Viridian Therapeutics, Inc."
    assert vrdn.resume_trade_time is None
    assert vrdn.source == "nasdaq_rss"


def test_nasdaq_parse_resume_populated():
    xml = (FIXTURES / "nasdaq_rss_sample.xml").read_bytes()
    events = nasdaq.parse(xml)
    insm = events[1]
    assert insm.symbol == "INSM"
    assert insm.is_resumed
    assert insm.resume_trade_time == "16:30:00"


def test_nasdaq_parse_luld():
    xml = (FIXTURES / "nasdaq_rss_sample.xml").read_bytes()
    events = nasdaq.parse(xml)
    aapl = events[2]
    assert aapl.symbol == "AAPL"
    assert aapl.reason_code == "LUDP"
    assert aapl.reason_description == "LULD Pause"


def test_nasdaq_parse_handles_garbage():
    """Should not raise on malformed input."""
    events = nasdaq.parse(b"<not><xml></valid>")
    assert events == []


def test_nyse_parse_basic_halt():
    csv_text = (FIXTURES / "nyse_csv_sample.csv").read_text()
    events = nyse.parse(csv_text)
    assert len(events) == 3

    arvn = events[0]
    assert arvn.symbol == "ARVN"
    assert arvn.exchange == "NYSE"
    assert arvn.halt_date == "2026-05-05"
    assert arvn.halt_time == "06:55:32"
    assert arvn.reason_code == "T1"  # normalized from "News pending"
    assert arvn.source == "nyse_csv"


def test_nyse_parse_normalizes_luld_pause():
    csv_text = (FIXTURES / "nyse_csv_sample.csv").read_text()
    events = nyse.parse(csv_text)
    idxx = events[1]
    assert idxx.symbol == "IDXX"
    assert idxx.reason_code == "LUDP"
    assert idxx.is_resumed
    assert idxx.resume_trade_time == "11:28:00"


def test_nyse_parse_h10():
    csv_text = (FIXTURES / "nyse_csv_sample.csv").read_text()
    events = nyse.parse(csv_text)
    repl = events[2]
    assert repl.symbol == "REPL"
    assert repl.reason_code == "H10"


def test_nyse_parse_empty():
    events = nyse.parse("Halt Date,Halt Time,Symbol,Name,Exchange,Reason,Resume Date,NYSE Resume Time\n")
    assert events == []


# --- Fix #4: halt_id canonicalizes the halt time ----------------------------
def test_halt_id_canonicalizes_time():
    unpadded = HaltEvent(symbol="ARVN", exchange="X", halt_date="2026-05-05",
                         halt_time="6:55:32", reason_code="T1", reason_description="")
    padded = HaltEvent(symbol="ARVN", exchange="X", halt_date="2026-05-05",
                       halt_time="06:55:32", reason_code="T1", reason_description="")
    assert unpadded.halt_id == padded.halt_id == ("ARVN", "2026-05-05", "06:55:32")


def test_halt_id_leaves_nonstandard_time_untouched():
    weird = HaltEvent(symbol="ARVN", exchange="X", halt_date="2026-05-05",
                      halt_time="pending", reason_code="T1", reason_description="")
    assert weird.halt_id == ("ARVN", "2026-05-05", "pending")


# --- Fix #2: fetch() raises on a soft feed failure (200 HTML/garbage) --------
def test_nasdaq_fetch_ok_on_valid_rss():
    xml = (FIXTURES / "nasdaq_rss_sample.xml").read_bytes()
    with patch("src.feeds.nasdaq.requests.get", return_value=_FakeResp(content=xml)):
        assert len(nasdaq.fetch()) == 3


def test_nasdaq_fetch_raises_on_html_soft_failure():
    """A 200 HTML error/challenge page must raise (fail loud), not parse to []."""
    html = b"<html><head><title>Access Denied</title></head><body>blocked</body></html>"
    with patch("src.feeds.nasdaq.requests.get", return_value=_FakeResp(content=html)):
        with pytest.raises(FeedParseError):
            nasdaq.fetch()


def test_nasdaq_fetch_raises_on_garbage_body():
    with patch("src.feeds.nasdaq.requests.get", return_value=_FakeResp(content=b"Access Denied")):
        with pytest.raises(FeedParseError):
            nasdaq.fetch()


def test_nyse_fetch_ok_on_valid_csv():
    csv_text = (FIXTURES / "nyse_csv_sample.csv").read_text()
    with patch("src.feeds.nyse.requests.get", return_value=_FakeResp(text=csv_text)):
        assert len(nyse.fetch()) == 3


def test_nyse_fetch_ok_on_empty_but_valid_csv():
    """Header row, no data rows = a genuine empty feed → no raise, no halts."""
    header = "Halt Date,Halt Time,Symbol,Name,Exchange,Reason,Resume Date,NYSE Resume Time\n"
    with patch("src.feeds.nyse.requests.get", return_value=_FakeResp(text=header)):
        assert nyse.fetch() == []


def test_nyse_fetch_raises_on_html_soft_failure():
    """A 200 HTML page has no valid CSV header → raise instead of '[] no halts'."""
    html = "<html><body>Access Denied</body></html>"
    with patch("src.feeds.nyse.requests.get", return_value=_FakeResp(text=html)):
        with pytest.raises(FeedParseError):
            nyse.fetch()


def test_nyse_fetch_raises_on_empty_body():
    with patch("src.feeds.nyse.requests.get", return_value=_FakeResp(text="")):
        with pytest.raises(FeedParseError):
            nyse.fetch()
