"""HCEvent — a classified health-care event from the PR wire.

A pure dataclass with no upward dependencies (mirrors news.types.NewsItem):
classify() builds one from a NewsItem, and halt_monitor._emit_hc_events stamps
the covered `symbol` per-attribution before rendering.
"""
from __future__ import annotations

from dataclasses import dataclass

# Event-type constants — the four families v1 fires (design §1).
TRIAL_READOUT = "trial_readout"
FDA_APPROVAL = "fda_approval"
CRL = "crl"
CLEARANCE = "clearance"

# Direction values for trial readouts.
DIR_MET = "met"
DIR_MISSED = "missed"
DIR_NA = "n/a"


@dataclass(frozen=True)
class HCEvent:
    """One classified HC event.

    classify() returns this with `symbol=""` (attribution is decided by the emit
    path from the item's already-extracted tickers ∩ universe); the emit path
    then produces a per-symbol copy via dataclasses.replace before rendering.

    Dedup key (built in the emit path): f"{news_id}|{symbol}|{event_type}".
    """

    news_id: str          # == NewsItem.url (dedup + reference)
    symbol: str           # covered ticker this event is attributed to ("" until emit)
    event_type: str       # TRIAL_READOUT | FDA_APPROVAL | CRL | CLEARANCE
    direction: str        # DIR_MET | DIR_MISSED | DIR_NA
    headline: str         # NewsItem.title, verbatim (SA reproduces issuer language)
    source: str           # "prnewswire" | "businesswire" | "globenewswire"
    url: str
    published_at: str     # ISO-8601 UTC
    phase: str = ""       # "1" | "2" | "3" | "" (trial readouts only)
    confidence: str = "high"  # high (PR-wire self-identified ticker) | medium (resolver, session 2)
    raw_industries: tuple[str, ...] = ()
