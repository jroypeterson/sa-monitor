# Coverage Manager — ticker/company-name mismatches surfaced from sa-monitor universe parse

While building the Phase 1 universe filter for the new `sa-monitor` project (which reads `Coverage Manager/exports/universe.csv` directly), I noticed five rows where the `Ticker` and `Company Name` fields appear to refer to different companies. These look like the original Coverage Manager row was for a now-delisted/repurposed ticker (most commonly a biotech that lost its listing) and the `Company Name` got overwritten when a different issuer started using the same symbol — likely from a `yfinance` enrichment pass that didn't check whether the ticker still pointed at the same security.

## Affected rows in `data/coverage_universe_tickers.csv`

| `Ticker` | Current `Company Name` | Likely intended (per `Sector (JP) = Biopharma`) | Status of intended company |
|---|---|---|---|
| `ADAP` | Automatic Data Processing Inc | Adaptimmune Therapeutics PLC | UK biotech, delisted from Nasdaq mid-2024; symbol may have been reassigned |
| `LIAN` | Li Auto Inc | LianBio (Hong Kong biotech) | Delisted 2024; company wound down |
| `MNK` | Minerals Technologies Inc | Mallinckrodt plc (specialty pharma) | Mallinckrodt is real and still trades; Minerals Technologies is `MTX` |
| `ZOM` | Zoominfo Technologies Inc | Zomedica (animal health pharma) | Zomedica still trades; Zoominfo is `ZI` |
| `FGEN` | Foresight Environmental Infrastructure (?) | FibroGen Inc (biotech) | Symbol reassigned 2025 after FibroGen delisting per public records — confirm current usage |

Each of these is in `Sector (JP) = "Biopharma"` with a blank `Subsector (JP)`, which is the tell — the row classification is from the original biotech, but the name was overwritten later.

## Suggested remediation

Two clean paths, depending on which is true for each ticker:

1. **If the original biotech is delisted and the ticker has been reassigned**: move the original Biopharma row to `data/delisted_tickers.csv` (per Coverage Manager's `CLAUDE.md`, the archive for acquired/de-listed names with last-known sector + market cap). Reassess whether the new issuer (ADP, LI, etc.) belongs in the universe at all under the post-2026-05-03 sector taxonomy.
2. **If the ticker is still the original biotech but the `Company Name` got overwritten by yfinance enrichment**: re-fetch via FMP or fix by hand and add a guard in `providers/yfinance_provider.py` so future enrichment doesn't overwrite a hand-curated name when yfinance returns a clearly different issuer.

## Why I'm filing this

The sa-monitor halt feed reads `Coverage Manager/exports/universe.csv` to filter exchange halts to my coverage universe. Mis-tagged Biopharma rows would cause mis-routed halt alerts — a halt on the real `LIAN` would have been tagged as a Biopharma halt; a halt on the symbol's current issuer (Li Auto) would have been routed against Biopharma sector rules and confused the alert template. I worked around it in sa-monitor by tightening the Phase 1 filter to also exclude `Biopharma` rows with blank `Subsector`, but that drops about 13 legitimate Large Pharma names (CSL, UCB, IPN, Chugai, Sun Pharma, Sandoz, Samsung Biologics, Bachem, Mayne Pharma, etc.) as collateral damage. Fixing the underlying Coverage Manager rows lets sa-monitor re-include those names later.

## Validation snippet

```python
import csv
from pathlib import Path

with Path("data/coverage_universe_tickers.csv").open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

for ticker in ("ADAP", "LIAN", "MNK", "ZOM", "FGEN"):
    for r in rows:
        if r.get("Ticker") == ticker:
            print(ticker, "→", r.get("Company Name"), "/",
                  r.get("Sector (JP)"), "/", r.get("Subsector (JP)"))
```

## Origin

Found 2026-05-05 during sa-monitor Deliverable 2 build. Captured in `sa-monitor/coverage-manager-issue-draft.md` for traceability.
