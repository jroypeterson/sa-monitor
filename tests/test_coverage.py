"""Smoke test for coverage Universe loading."""
import json

import pytest

from src.coverage import Universe


def test_universe_loads_from_default_path():
    u = Universe()
    assert len(u) >= 1000  # 2026-06-16: biotech re-included (~1095); was ~554 in Phase 1
    # Spot-check a known ticker
    assert "IDXX" in u
    meta = u.get("IDXX")
    assert meta is not None
    assert meta.sector == "Healthcare Services"


def test_universe_includes_biotech():
    """Biotech re-included 2026-06-16 (was excluded in Phase 1) — VRTX now present."""
    u = Universe()
    assert "VRTX" in u
    meta = u.get("VRTX")
    assert meta is not None
    assert meta.subsector == "Biotech"


def test_universe_keeps_large_pharma():
    u = Universe()
    assert "MRK" in u
    assert "PFE" in u


def test_universe_membership_case_insensitive():
    u = Universe()
    assert "idxx" in u
    assert "Idxx" in u


def test_universe_get_returns_none_for_missing():
    u = Universe()
    assert u.get("NONEXISTENT") is None


def test_universe_rejects_wrong_schema_version(tmp_path):
    """A schema-version mismatch must fail loud, not silently misread."""
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"schema_version": 99, "tickers": {"IDXX": {}}}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        Universe(p)


def test_universe_rejects_empty_universe(tmp_path):
    """A zero-ticker universe would silently drop every halt — must fail loud."""
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"schema_version": 1, "tickers": {}}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="zero tickers"):
        Universe(p)
