"""Build sa_monitor_universe.json from Coverage Manager exports.

Phase 1 filter (locked 2026-05-05):
- Drop Subsector (JP) == "Biotech".
- Drop Biopharma rows with blank Subsector (Coverage Manager has not classified them yet).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CM_EXPORTS = REPO_ROOT.parent / "Coverage Manager" / "exports"
CM_UNIVERSE_CSV = CM_EXPORTS / "universe.csv"
CM_UNIVERSE_STATUS = CM_EXPORTS / "universe_status.json"
OUTPUT_PATH = REPO_ROOT / "data" / "sa_monitor_universe.json"

EXCLUDE_SUBSECTOR = {"Biotech"}
EXCLUDE_BIOPHARMA_BLANK_SUBSECTOR = True


def main() -> None:
    status = json.loads(CM_UNIVERSE_STATUS.read_text())
    if status.get("schema_version") != 3:
        raise SystemExit(f"Coverage Manager schema_version {status.get('schema_version')!r}, expected 3")
    if not status.get("validation_passed"):
        raise SystemExit(f"Coverage Manager universe failed validation: {status.get('validation_errors')!r}")

    with CM_UNIVERSE_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    tickers: dict[str, dict] = {}
    excluded_subsector_count = 0
    excluded_blank_biopharma_count = 0
    excluded_no_ticker = 0
    sector_counter: Counter[str] = Counter()

    for r in rows:
        ticker = (r.get("Ticker") or "").strip()
        if not ticker:
            excluded_no_ticker += 1
            continue
        subsector = (r.get("Subsector (JP)") or "").strip()
        sector = (r.get("Sector (JP)") or "").strip()
        if subsector in EXCLUDE_SUBSECTOR:
            excluded_subsector_count += 1
            continue
        if EXCLUDE_BIOPHARMA_BLANK_SUBSECTOR and sector == "Biopharma" and not subsector:
            excluded_blank_biopharma_count += 1
            continue
        tickers[ticker] = {
            "name": (r.get("Company Name") or "").strip(),
            "sector": sector,
            "subsector": subsector,
            "sub_subsector": (r.get("Sub-subsector (JP)") or "").strip(),
            "core": (r.get("Core") or "").strip(),
            "exchange": (r.get("Exchange") or "").strip(),
            "country_hq": (r.get("Country (HQ)") or "").strip(),
            "currency": (r.get("Currency") or "").strip(),
        }
        sector_counter[sector] += 1

    out = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "csv_path": str(CM_UNIVERSE_CSV),
            "status_path": str(CM_UNIVERSE_STATUS),
            "cm_schema_version": status.get("schema_version"),
            "cm_dataset_version": status.get("dataset_version"),
        },
        "filter": {
            "rule": "Phase 1 lenient Biopharma exclusion + blank-subsector Biopharma exclusion",
            "exclude_subsector": sorted(EXCLUDE_SUBSECTOR),
            "exclude_biopharma_with_blank_subsector": EXCLUDE_BIOPHARMA_BLANK_SUBSECTOR,
            "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        },
        "counts": {
            "rows_in_source": len(rows),
            "rows_with_no_ticker": excluded_no_ticker,
            "rows_excluded_by_subsector_filter": excluded_subsector_count,
            "rows_excluded_blank_biopharma": excluded_blank_biopharma_count,
            "tickers_in_filtered_universe": len(tickers),
            "by_sector": dict(sector_counter.most_common()),
        },
        "tickers": dict(sorted(tickers.items())),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT_PATH}", flush=True)
    print(f"  source rows: {len(rows)}", flush=True)
    print(f"  excluded (Biotech subsector): {excluded_subsector_count}", flush=True)
    print(f"  excluded (blank-subsector Biopharma): {excluded_blank_biopharma_count}", flush=True)
    print(f"  excluded (blank ticker): {excluded_no_ticker}", flush=True)
    print(f"  filtered universe size: {len(tickers)}", flush=True)
    print(f"  by Sector (JP):", flush=True)
    for sector, count in sector_counter.most_common():
        print(f"    {sector or '(blank)'}: {count}", flush=True)


if __name__ == "__main__":
    main()
