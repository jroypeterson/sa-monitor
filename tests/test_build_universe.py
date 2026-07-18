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
