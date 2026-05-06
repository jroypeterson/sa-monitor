"""Smoke test for coverage Universe loading."""
from src.coverage import Universe


def test_universe_loads_from_default_path():
    u = Universe()
    assert len(u) >= 500  # Phase 1 expects 554
    # Spot-check a known ticker
    assert "IDXX" in u
    meta = u.get("IDXX")
    assert meta is not None
    assert meta.sector == "Healthcare Services"


def test_universe_excludes_biotech():
    """VRTX (Biotech subsector) was deliberately excluded by the Phase 1 filter."""
    u = Universe()
    assert "VRTX" not in u


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
