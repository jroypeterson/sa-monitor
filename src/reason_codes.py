"""Halt-reason-code → human-readable description.

Authoritative source: https://www.nasdaqtrader.com/trader.aspx?id=tradehaltcodes
NYSE halt-reason strings observed empirically from
https://www.nyse.com/api/trade-halts/current/download.

Phase 1 default filter (per phase1-data-sources.md §3): include T1, T2, T5, T6,
T12, H4, H9, H10, H11, M1, LUDP, LUDS, MWC1/2/3, MWCO, MWCQ. Exclude T8, M2,
O1, IPO* by default but log them.

The values here are intentionally short — they appear inside the halt
notification rendered in `template.render_halt()`, where space matters.
"""
from __future__ import annotations

# Nasdaq's published reason codes (the canonical industry list — used by NYSE
# too via the consolidated tape). Keys are the literal codes as published in
# Nasdaq Trader's RSS feed. Values are short human descriptions.
NASDAQ_REASON_CODES: dict[str, str] = {
    "T1": "News Pending",
    "T2": "News Released",
    "T5": "Single Stock Trading Pause (10% in 5 min)",
    "T6": "Extraordinary Market Activity",
    "T8": "ETP / EXTL halt",
    "T12": "Additional Information Requested",
    "H4": "Non-Compliance with Listing Requirements",
    "H9": "Not Current with Filings",
    "H10": "SEC Trading Suspension",
    "H11": "Regulatory Concern (other market)",
    "M1": "Corporate Action",
    "M2": "Quotation Not Available",
    "O1": "Operations Halt",
    "IPO1": "IPO Issue Not Yet Trading",
    "IPOQ": "IPO Quotation Initiated",
    "IPO2": "IPO Quotation",
    "LUDP": "LULD Pause",
    "LUDS": "LULD Trading Pause - Straddle Condition",
    "MWC1": "Market-Wide Circuit Breaker Level 1",
    "MWC2": "Market-Wide Circuit Breaker Level 2",
    "MWC3": "Market-Wide Circuit Breaker Level 3",
    "MWCO": "MWCB Order halt",
    "MWCQ": "MWCB Quote halt",
    "R4": "Resumption Trade Time",
    "R1": "Resumption Quote Time",
}

# NYSE's API publishes "Reason" as a free-text string (e.g. "News pending",
# "News Released", "LULD pause"). Map common strings back to the canonical
# Nasdaq code so dedup by (symbol, halt_date, halt_time) works across feeds.
NYSE_REASON_TO_CODE: dict[str, str] = {
    "news pending": "T1",
    "news released": "T2",
    "luld pause": "LUDP",
    "luld trading pause": "LUDP",
    "regulatory halt": "H11",
    "single stock trading pause": "T5",
    "extraordinary market activity": "T6",
    "operations halt": "O1",
    "sec trading suspension": "H10",
    "non-compliance": "H4",
    "additional information requested": "T12",
    "ipo issue not yet trading": "IPO1",
    "ipo quotation": "IPOQ",
    "corporate action": "M1",
    "market-wide circuit breaker level 1": "MWC1",
    "market-wide circuit breaker level 2": "MWC2",
    "market-wide circuit breaker level 3": "MWC3",
}

# Phase 1 emit-by-default filter (codes that fire alerts). T8, M2, O1, IPO*
# are excluded by default but still logged.
PHASE1_EMIT_CODES: set[str] = {
    "T1", "T2", "T5", "T6", "T12",
    "H4", "H9", "H10", "H11",
    "M1",
    "LUDP", "LUDS",
    "MWC1", "MWC2", "MWC3", "MWCO", "MWCQ",
}


def describe(code: str) -> str:
    """Return human-readable description for a halt code, or the code itself
    if not in the table (so unknown codes don't drop information)."""
    return NASDAQ_REASON_CODES.get(code.upper(), code)


def normalize_nyse_reason(reason: str) -> str:
    """Map a free-text NYSE reason string to the canonical Nasdaq code.
    Returns the original string upper-cased if no mapping is found."""
    key = (reason or "").strip().lower()
    return NYSE_REASON_TO_CODE.get(key, reason.upper())


def is_phase1_emit_code(code: str) -> bool:
    """Whether a halt-reason code should fire a Slack alert in Phase 1."""
    return code.upper() in PHASE1_EMIT_CODES
