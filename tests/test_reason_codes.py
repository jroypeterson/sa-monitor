"""Tests for reason_codes module."""
from src.reason_codes import (
    describe,
    is_phase1_emit_code,
    normalize_nyse_reason,
)


def test_describe_known_code():
    assert describe("T1") == "News Pending"
    assert describe("LUDP") == "LULD Pause"
    assert describe("H10") == "SEC Trading Suspension"


def test_describe_unknown_code_returns_input():
    assert describe("ZZ99") == "ZZ99"


def test_describe_lowercase_normalized():
    assert describe("t1") == "News Pending"


def test_normalize_nyse_reason_known():
    assert normalize_nyse_reason("News pending") == "T1"
    assert normalize_nyse_reason("LULD pause") == "LUDP"
    assert normalize_nyse_reason("SEC Trading Suspension") == "H10"


def test_normalize_nyse_reason_case_insensitive():
    assert normalize_nyse_reason("news pending") == "T1"
    assert normalize_nyse_reason("NEWS PENDING") == "T1"


def test_normalize_nyse_reason_unknown_passes_through_uppercase():
    assert normalize_nyse_reason("Some New Reason") == "SOME NEW REASON"


def test_normalize_nyse_reason_empty():
    assert normalize_nyse_reason("") == ""


def test_phase1_emit_codes_include_critical():
    assert is_phase1_emit_code("T1")
    assert is_phase1_emit_code("T2")
    assert is_phase1_emit_code("LUDP")
    assert is_phase1_emit_code("H10")
    assert is_phase1_emit_code("MWC1")


def test_phase1_emit_codes_exclude_low_signal():
    assert not is_phase1_emit_code("T8")
    assert not is_phase1_emit_code("M2")
    assert not is_phase1_emit_code("O1")
    assert not is_phase1_emit_code("IPO1")
