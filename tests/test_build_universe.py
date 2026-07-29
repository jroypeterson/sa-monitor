"""Guard test for scripts/build_universe.py fail-loud behavior.

Loads the script by path (scripts/ is not a package) and drives main() against
monkeypatched CM export paths so no live CM data or the real universe.json is
touched.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_universe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_universe", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_universe_refuses_empty(tmp_path, monkeypatch):
    """A header-only CM CSV that still passes the status check must NOT produce a
    zero-ticker universe.json — build must abort (SystemExit) instead."""
    mod = _load_module()

    status = tmp_path / "universe_status.json"
    status.write_text(json.dumps({
        "schema_version": 3,
        "validation_passed": True,
        "dataset_version": "test",
    }), encoding="utf-8")
    # Header-only CSV -> zero data rows -> zero tickers.
    csv_path = tmp_path / "universe.csv"
    csv_path.write_text(
        "Ticker,Company Name,Sector (JP),Subsector (JP)\n", encoding="utf-8"
    )
    out_path = tmp_path / "sa_monitor_universe.json"

    monkeypatch.setattr(mod, "CM_UNIVERSE_STATUS", status)
    monkeypatch.setattr(mod, "CM_UNIVERSE_CSV", csv_path)
    monkeypatch.setattr(mod, "OUTPUT_PATH", out_path)

    with pytest.raises(SystemExit, match="EMPTY"):
        mod.main()

    # And it must not have written a bad artifact.
    assert not out_path.exists()


# --- CM exports schema gate -------------------------------------------------
# Phase 1 of the CM v4 (dual-ISIN) release widened this gate from `!= 3` to a
# frozenset {3, 4} so sa-monitor is green both before and after CM flips.
# NARROW TO {4} in phase 4 — `test_accepts_schema_v3` becomes a rejection then.

_ROWS = (
    "Ticker,Company Name,Sector (JP),Subsector (JP),Sub-subsector (JP),"
    "Core,Exchange,Country (HQ),Currency\n"
    "IDXX,IDEXX Laboratories,MedTech,Diagnostics,,Y,NMS,US,USD\n"
    "LLY,Eli Lilly,Biopharma,Large Pharma,,Y,NYQ,US,USD\n"
)


def _wire(tmp_path, monkeypatch, schema_version, csv_text=_ROWS):
    mod = _load_module()
    status = tmp_path / "universe_status.json"
    status.write_text(json.dumps({
        "schema_version": schema_version,
        "validation_passed": True,
        "dataset_version": "test",
    }), encoding="utf-8")
    csv_path = tmp_path / "universe.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    out_path = tmp_path / "sa_monitor_universe.json"
    monkeypatch.setattr(mod, "CM_UNIVERSE_STATUS", status)
    monkeypatch.setattr(mod, "CM_UNIVERSE_CSV", csv_path)
    monkeypatch.setattr(mod, "OUTPUT_PATH", out_path)
    return mod, out_path


@pytest.mark.parametrize("version", [3, 4])
def test_accepted_schema_versions_build_a_non_empty_universe(
    tmp_path, monkeypatch, version
):
    """Both sides of the flip must produce tickers. Asserting only "it didn't
    raise" would miss a zero-ticker build, which is the BOM failure signature."""
    mod, out_path = _wire(tmp_path, monkeypatch, version)
    mod.main()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["tickers"], "built a zero-ticker universe"
    assert set(payload["tickers"]) == {"IDXX", "LLY"}
    assert payload["source"]["cm_schema_version"] == version


@pytest.mark.parametrize("version", [2, 5, 99])
def test_schema_outside_the_window_still_exits_loudly(tmp_path, monkeypatch, version):
    mod, out_path = _wire(tmp_path, monkeypatch, version)
    with pytest.raises(SystemExit, match="schema_version"):
        mod.main()
    assert not out_path.exists()


def test_schema_error_names_the_accepted_set(tmp_path, monkeypatch):
    """The operator reading the exit line needs the window, not one number."""
    mod, _ = _wire(tmp_path, monkeypatch, 5)
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert "[3, 4]" in str(exc.value)


def test_v4_extra_identity_columns_are_inert(tmp_path, monkeypatch):
    """v4 adds `ISIN (Primary Listing)` + `Country (Incorporation)`. Every field
    here is read by name, so unknown columns must not disturb the build."""
    csv_text = (
        "Ticker,Company Name,Sector (JP),Subsector (JP),Sub-subsector (JP),"
        "Core,Exchange,Country (HQ),Currency,ISIN,ISIN (Primary Listing),"
        "Country (Incorporation)\n"
        "AZN,AstraZeneca PLC,Biopharma,Large Pharma,,Y,NYQ,GB,USD,"
        "US0463531089,GB0009895292,GB\n"
    )
    mod, out_path = _wire(tmp_path, monkeypatch, 4, csv_text=csv_text)
    mod.main()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert list(payload["tickers"]) == ["AZN"]
    assert payload["tickers"]["AZN"]["country_hq"] == "GB"
