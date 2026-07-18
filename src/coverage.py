"""Load the sa-monitor coverage universe (built by scripts/build_universe.py)
and provide a simple in-universe membership test plus per-ticker metadata
lookup (sector, subsector, name, etc.).

The data file is `data/sa_monitor_universe.json` — produced by filtering
Coverage Manager's exports/universe.csv per the Phase 1 lenient + blank-
subsector Biopharma exclusion rule.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = REPO_ROOT / "data" / "sa_monitor_universe.json"


@dataclass(frozen=True)
class TickerMeta:
    symbol: str
    name: str
    sector: str
    subsector: str
    sub_subsector: str = ""
    core: str = ""
    exchange: str = ""
    country_hq: str = ""
    currency: str = ""


class Universe:
    """In-memory ticker universe with O(1) membership + metadata lookup."""

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        self._tickers: dict[str, TickerMeta] = {}
        self._meta_payload: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(
                f"sa-monitor universe not found at {self.path}. "
                f"Run `python scripts/build_universe.py` to generate it."
            )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        # Fail-loud on a schema mismatch: this file is self-produced by
        # scripts/build_universe.py with schema_version==1. A mismatch means the
        # producer and consumer disagree on shape — mirror the same guard that
        # build_universe.py applies to the CM export and state.py applies to its
        # own file, rather than silently misreading it into a partial universe.
        schema_version = payload.get("schema_version")
        if schema_version != 1:
            raise ValueError(
                f"sa-monitor universe at {self.path} has schema_version "
                f"{schema_version!r}, expected 1. Rebuild with "
                f"`python scripts/build_universe.py`."
            )
        self._meta_payload = {k: v for k, v in payload.items() if k != "tickers"}
        for symbol, meta in payload.get("tickers", {}).items():
            self._tickers[symbol.upper()] = TickerMeta(
                symbol=symbol,
                name=meta.get("name", ""),
                sector=meta.get("sector", ""),
                subsector=meta.get("subsector", ""),
                sub_subsector=meta.get("sub_subsector", ""),
                core=meta.get("core", ""),
                exchange=meta.get("exchange", ""),
                country_hq=meta.get("country_hq", ""),
                currency=meta.get("currency", ""),
            )
        # A zero-ticker universe is never operationally valid for a LIVE
        # monitor — it would silently filter EVERY covered halt out-of-universe
        # (meta is None) and emit nothing, indistinguishable from a quiet
        # market. Fail loud so a stale/empty/corrupt build can't cause a silent
        # 100% miss.
        if not self._tickers:
            raise ValueError(
                f"sa-monitor universe at {self.path} loaded zero tickers. "
                f"Refusing to run against an empty universe (would silently "
                f"drop every halt). Rebuild with "
                f"`python scripts/build_universe.py`."
            )

    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in self._tickers

    def get(self, symbol: str) -> Optional[TickerMeta]:
        return self._tickers.get(symbol.upper())

    def __len__(self) -> int:
        return len(self._tickers)

    @property
    def filter_rule(self) -> str:
        return self._meta_payload.get("filter", {}).get("rule", "")

    @property
    def cm_dataset_version(self) -> str:
        return self._meta_payload.get("source", {}).get("cm_dataset_version", "")
