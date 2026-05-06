"""Tests for Nasdaq RSS + NYSE CSV parsers using fixture data."""
from pathlib import Path

from src.feeds import nasdaq, nyse

FIXTURES = Path(__file__).parent / "fixtures"


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
