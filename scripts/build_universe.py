"""Build sa_monitor_universe.json from Coverage Manager exports.

Universe filter history:
- Phase 1 (locked 2026-05-05): dropped Subsector (JP) == "Biotech" and blank-subsector
  Biopharma, because biotech halts are frequent/binary and were out of Phase 1 scope.
- 2026-06-16: **biotech re-included** (JP decision) — biotech halts are now the
  real-time signal that feeds the biotech catalyst/triage loop (see the root
  `biotech_catalyst_architecture_plan.md`). Both exclusions are disabled below;
  the filter mechanism is kept (empty/false) so it's trivially reversible.
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

# Biotech re-included 2026-06-16 — both exclusions disabled (empty / False).
# Re-exclude by restoring {"Biotech"} / True.
EXCLUDE_SUBSECTOR: set[str] = set()
EXCLUDE_BIOPHARMA_BLANK_SUBSECTOR = False

# TEMPORARY window for the CM v4 dual-ISIN release (2026-07-28); NARROW TO {4}
# in phase 4. CM adds `ISIN (Primary Listing)` + `Country (Incorporation)` and
# flips 3 -> 4; this script reads every field by name below, so the two new
# columns are inert for it and only the gate has to move. Widened here first,
# while CM still publishes 3, so both sides of the flip are green on disk.
_ACCEPTED_CM_SCHEMA = frozenset({3, 4})


def main() -> None:
    status = json.loads(CM_UNIVERSE_STATUS.read_text())
    if status.get("schema_version") not in _ACCEPTED_CM_SCHEMA:
        raise SystemExit(
            f"Coverage Manager schema_version {status.get('schema_version')!r}, "
            f"expected one of {sorted(_ACCEPTED_CM_SCHEMA)}"
        )
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

    # Fail loud rather than write a zero-ticker universe: a header-only or
    # truncated CM CSV (that still passes the status schema/validation check
    # above) would otherwise produce an empty universe.json, and the LIVE
    # monitor would silently filter every covered halt out-of-universe. Better
    # to abort the build and keep the last-good file in place.
    if not tickers:
        raise SystemExit(
            f"build_universe: filtered universe is EMPTY (0 tickers) from "
            f"{len(rows)} source rows in {CM_UNIVERSE_CSV}. Refusing to write a "
            f"zero-ticker universe.json (would cause a silent 100% halt-alert "
            f"outage). Check the CM export."
        )

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
            "rule": "2026-06-16: biotech re-included; no sector/subsector exclusions",
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
    # encoding="utf-8" is REQUIRED: ensure_ascii=False emits raw non-ASCII (accented
    # European biotech names like "ALK-Abelló", "genOway Société"); without an explicit
    # encoding, write_text() uses the Windows locale codepage (cp1252) when regenerated
    # on JP's machine, planting bytes that crash the UTF-8 reader on the Linux runner
    # (the 2026-06-16 → 06-23 100% halt-monitor outage). Pin it so it can't regress.
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
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
