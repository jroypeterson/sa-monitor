"""Precision-biased keyword classifier: NewsItem -> Optional[HCEvent].

Design of record: research/sa_monitor_hc_event_wire_design_2026-07-13.md §3.
Rules are anchored to the LOCKED real headlines in template-library.md
§15 (Phase-N primary MISSED), §16 (FDA approval), §19 (Phase-N primary MET).

Philosophy — "miss over misfire" (design §7): a wrong "Phase 3 met" or "FDA
approval" alert costs more trust than a missed one. Every rule requires the
headline to CLEARLY match a completed action. Ambiguous, future-tense,
procedural, or presentation headlines return None.

classify() only proposes an event *type/direction/phase*; it never decides
whether to fire. The universe filter + attribution + dedup live in
halt_monitor._emit_hc_events. classify() returns an HCEvent with symbol="".
"""
from __future__ import annotations

import re
from typing import Optional

from ..news.types import NewsItem
from .types import (
    CLEARANCE,
    CRL,
    DIR_MET,
    DIR_MISSED,
    DIR_NA,
    FDA_APPROVAL,
    TRIAL_READOUT,
    HCEvent,
)

# --------------------------------------------------------------------------
# Trial readout
# --------------------------------------------------------------------------

# "Phase 1/2/3" (also "Phase 2B", "Phase 1/2") — capture the leading digit.
_PHASE = re.compile(r"\bphase\s*([123])", re.I)

# Result attached to the PRIMARY (or co-/dual primary) endpoint. Tying the
# verb to "primary" (rather than matching "met"/"missed" anywhere) keeps the
# reported DIRECTION faithful, which is the harmful failure mode to avoid.
_MET_PRIMARY = re.compile(
    r"\b(met|meets|achieved|achieves|hit|reached)\b"
    r"(?:\s+(?:its|the|all|both|all\s+of\s+its))?"
    r"(?:\s+(?:co-|dual|two|three|multiple))?"
    r"\s+(?:co-)?primary\b",
    re.I,
)
# Anchored to primary/endpoint so "did not meet enrollment target / guidance"
# (with a stray Phase in the title) can't read as a failed readout.
_MISSED_PRIMARY = re.compile(
    r"\b(did\s+not\s+meet|does\s+not\s+meet|failed\s+to\s+meet|fails\s+to\s+meet"
    r"|missed|misses|did\s+not\s+achieve|does\s+not\s+achieve)\b"
    r"(?:\s+(?:its|the|both|all|all\s+of\s+its))?"
    r"(?:\s+(?:co-|dual))?"
    r"\s+(?:primary|co-primary|endpoint)",
    re.I,
)
# A topline-data announcement with no explicit met/missed in the headline is
# still a genuine readout crossing the wire — fired at direction n/a.
_TOPLINE = re.compile(r"\btop-?line\b", re.I)

# Future / procedural / presentation headlines that mention a Phase but are NOT
# a readout. If ANY of these match, the trial-readout path returns None. This
# is the primary defense for the negative test set.
_TRIAL_NEGATIVE = re.compile(
    r"\bpresent"          # present / presents / presented / presentation / presenting
    r"|\bto\s+report\b|\bwill\s+report\b"
    r"|\bto\s+announce\b|\bto\s+host\b|\bto\s+provide\b|\bto\s+release\b"
    r"|\bto\s+webcast\b|\bwebcast\b|\bconference\s+call\b|\binvestor\s+day\b"
    r"|\bposter\b|\bat\s+the\s+\w+.*(?:conference|congress|meeting|symposium)"
    r"|\binitiat"          # initiate / initiation / initiates
    r"|\bcommenc"          # commence / commences / commencement
    r"|\bfirst[\s-]patient\b|\bdosing\s+of\b|\bdoses\s+(?:the\s+)?first\b"
    r"|\bfirst\s+patient\s+dosed\b"
    r"|\benroll"           # enroll / enrolls / enrolled / enrollment
    r"|\btrial\s+design\b|\bstudy\s+design\b"
    r"|\bto\s+begin\b|\bplans?\s+to\b|\bexpects?\s+to\b"
    r"|\bon\s+track\b|\bdesign(?:s|ed)?\s+to\s+evaluate\b"
    r"|\bcompletes?\s+enrollment\b"
    # F4: future-timeline readouts ("topline data expected in Q4") are NOT a
    # readout that happened. Requires a timeline token after expected/anticipated
    # so "met primary, better than expected" still fires.
    r"|\bexpected\s+(?:in|by|during|for|later|this|next|early|mid|late|soon|shortly|imminent|upcoming|coming|q[1-4]|h[12]|first|second|third|fourth|20\d\d)"
    r"|\banticipat\w*\s+(?:in|by|during|for|later|this|next|early|mid|late|soon|shortly|imminent|upcoming|coming|q[1-4]|h[12]|20\d\d)"
    r"|\bto\s+read\s+out\b|\breadout\s+(?:expected|anticipated|on\s+track|in|by|soon|shortly)\b"
    # round-2 #1: more future-readout phrasings. NOT bare "expected" — a MET
    # readout that merely says "better than expected" must still fire.
    r"|\bto\s+report\s+(?:its\s+)?topline\b|\bexpects?\s+(?:to\s+report\s+)?topline\b"
    r"|\btopline\b(?:\W+\w+){0,6}?\W+(?:expected|anticipated|on\s+track|in\s+q[1-4]|in\s+h[12]|in\s+20\d\d)"
    r"|\bdata\s+(?:readout|expected)\s+(?:in|by)\b|\bto\s+be\s+reported\b",
    re.I,
)


def _classify_trial(title: str, item: NewsItem) -> Optional[HCEvent]:
    m_phase = _PHASE.search(title)
    if not m_phase:
        return None

    # round-3 FN-A: a COMPLETED result wins over a co-mentioned call/presentation.
    # "Announces Phase 3 Met Primary Endpoint; Conference Call Today" is the
    # STANDARD readout PR — an explicit met/missed-PRIMARY result IS a readout
    # and fires regardless of _TRIAL_NEGATIVE. The future/procedural veto applies
    # ONLY to the topline-without-explicit-result path, where "to be presented /
    # expected in Q4" genuinely means the readout hasn't happened yet.
    if _MISSED_PRIMARY.search(title):
        direction = DIR_MISSED
    elif _MET_PRIMARY.search(title):
        direction = DIR_MET
    elif _TOPLINE.search(title) and not _TRIAL_NEGATIVE.search(title):
        direction = DIR_NA
    else:
        return None  # Phase present but no fired result grammar → not a readout

    return _build(item, TRIAL_READOUT, direction, phase=m_phase.group(1))


# --------------------------------------------------------------------------
# FDA regulatory actions
# --------------------------------------------------------------------------

# Action-verb-anchored approval grammar. Deliberately does NOT match bare
# "FDA approval" so pending/procedural headlines ("PDUFA date for FDA approval
# decision", "seeking FDA approval") don't fire.
_APPROVAL = re.compile(
    r"\bfda\s+approves\b"
    r"|\bfda\s+approved\b"
    r"|\bfda\s+approval\s+of\b"
    r"|\breceive[sd]?\s+fda\s+approval\b"
    r"|\bgranted\s+fda\s+approval\b"
    r"|\bwins?\s+fda\s+approval\b"
    r"|\bsecure[sd]?\s+fda\s+approval\b"
    r"|\bgains?\s+fda\s+approval\b"
    r"|\bfda\s+grants?\s+(?:full\s+|accelerated\s+|traditional\s+|marketing\s+)?approval\b"
    r"|\bfda\s+has\s+granted\s+approval\b"
    r"|\bapproved\s+by\s+the\s+fda\b",
    re.I,
)
# Pending-APPLICATION framing (round-3 FN-B). The old broad suppressor (pdufa /
# accepts / submits / submission / application for / pre-market notification /
# advisory committee …) was REMOVED as redundant AND harmful: the grant verbs in
# _APPROVAL/_CLEARANCE already fail to match a purely-pending headline ("FDA
# accepts NDA", "FDA grants Priority Review to X") so it returns None without
# them — while those nouns wrongly vetoed COMPLETED actions ("FDA approves
# supplemental application for X", "FDA clears 510(k) premarket notification").
#
# What remains is only the one weak, ambiguous grant alternative — the noun
# phrase "FDA approval of / FDA clearance" — appearing in an unmistakably
# PENDING construction: "…for (FDA) approval/clearance" (application for /
# files for / petition for / resubmits application for), and bare "resubmi…".
# Completed self-approvals never read "FOR approval" (they read "receives FDA
# approval", "on FDA approval of", "highlights FDA approval of").
_REG_PENDING_APP = re.compile(
    r"\bfor\s+(?:(?:the|a|an|its|full|final|marketing|us|u\.s\.|potential"
    r"|supplemental|expanded|conditional|initial)\s+){0,2}"
    r"(?:fda\s+)?(?:approval|clearance)\b"
    r"|\bresubmi\w*",
    re.I,
)

# Future / intent framing toward a grant that hasn't happened yet (round-2 #2):
# "targets/expects/pending/plans to/seeks/on track for FDA clearance", and the
# reverse "FDA clearance expected/pending". Anchored to the grant noun (with a
# whitelisted determiner/adjective window) so an approval that merely CONTAINS
# "expected" ("approved sooner than expected", "better than expected") is NOT
# suppressed. Fillers are a closed set of determiners/adjectives, never verbs,
# so "plans to commercialize following FDA approval" (a real approval) doesn't
# get vetoed.
_REG_FUTURE_INTENT = re.compile(
    # intent-then-noun
    r"\b(?:pending|expect\w*|anticipat\w*|target\w*|plan\w*\s+to|intends?\s+to"
    r"|seek\w*|on\s+track\s+(?:for|to))\s+"
    r"(?:(?:the|a|an|its|potential|possible|marketing|regulatory|full|final|us|u\.s\.)\s+){0,2}"
    r"(?:fda\s+)?(?:approval|clearance|authorization|de\s+novo)\b"
    r"|"
    # noun-then-intent
    r"\b(?:fda\s+)?(?:approval|clearance|authorization)\b\s+"
    r"(?:(?:is|remains|still|now|currently)\s+){0,2}"
    r"(?:pending|expect\w*|anticipat\w*|target\w*|on\s+track)\b",
    re.I,
)

# Denial / rejection grammar (F2). A rejection must NEVER read as a grant. v1
# has no "rejection" event type, so a plain "did not receive approval" headline
# → None (missing it is far safer than inverting it to an approval). Gates BOTH
# approval and clearance. NOT applied to trial readouts (which have their own
# missed-endpoint direction) or to CRL (the rejection event we DO fire).
_REG_DENIAL = re.compile(
    r"\bdid\s+not\b|\bdoes\s+not\b|\bdid\s*n[’']?t\b|\bdoes\s*n[’']?t\b"
    r"|\bfailed\s+to\b|\bfails\s+to\b"
    r"|\bnot\s+(?:receive|receiv\w+|win|won|gain\w*|secure\w*|grant\w*|approv\w+|clear\w+)\b"
    r"|\bdenie[sd]\b|\bdenial\b|\bdeclin\w*\s+to\s+approve\b"
    r"|\breject(?:s|ed|ion)?\b|\bnot\s+approved\b|\bunapproved\b"
    r"|\bwithdraw\w*\b|\brescind\w*\b|\brevoke[sd]?\b",
    re.I,
)

# Commentary / competitor framing (F3): an issuer reacting to SOMEONE ELSE's
# FDA action. _emit_hc_events would mis-attribute it to the commenting issuer.
# round-3 FN-C: NARROWED to CLEAR third-party-commentary verbs only. The generic
# highlights/notes/discusses/cites/references were DROPPED — they also suppressed
# genuine self-approval PRs ("Acme highlights FDA approval of ITS drug"). The
# competitor case they caught is rare enough to accept as a residual FP under
# miss-over-misfire.
_REG_COMMENTARY = re.compile(
    r"\bcomment(?:s|ary|ing|ed)?\s+on\b|\bcommentary\b"
    r"|\bcongratulat\w+|\bapplaud\w*|\bwelcome[sd]?\b|\breact[s]?\s+to\b"
    r"|\brespond[s]?\s+to\b|\bissues?\s+statement\b"
    r"|\bstatement\s+(?:on|regarding|re)\b",
    re.I,
)

# CRL (F5). Must NOT match bare \bcrl\b — CRL is also the ticker for Charles
# River Laboratories, a COVERED name ("CRL Announces … Financial Results").
# Require the full phrase or a regulatory-CRL idiom.
_CRL = re.compile(
    r"\bcomplete\s+response\s+letter\b"
    r"|\breceiv\w*\s+(?:a\s+)?crl\b"
    r"|\bcrl\s+from\s+(?:the\s+)?fda\b"
    r"|\bissue[sd]?\s+(?:a\s+)?crl\b"
    r"|\bfda\s+issue[sd]?\s+(?:a\s+)?crl\b",
    re.I,
)

# Medtech clearance. Requires a completed clearance action — bare adjective
# "FDA-cleared" (e.g. "operates an FDA-cleared facility") must NOT match.
_CLEARANCE = re.compile(
    r"\bfda\s+clears\b"
    r"|\bfda\s+clearance\b"
    r"|\breceive[sd]?\s+fda\s+clearance\b"
    r"|\b510\(k\)\s+clearance\b"
    r"|\bgranted\s+510\(k\)\b"
    r"|\bde\s+novo\s+(?:clearance|authorization|grant)\b"
    r"|\bpma\s+approval\b"
    r"|\bfda\s+grants?\s+(?:de\s+novo|510)\b",
    re.I,
)


def _reg_suppressed(title: str) -> bool:
    """A grant (approval or clearance) is suppressed only when the headline is
    NOT a completed action: a pending-application framing, a future/intent
    framing toward the grant, a denial/rejection, or third-party commentary.
    A completed action ("FDA approves…", "receives FDA approval") passes."""
    return bool(
        _REG_PENDING_APP.search(title)
        or _REG_FUTURE_INTENT.search(title)
        or _REG_DENIAL.search(title)
        or _REG_COMMENTARY.search(title)
    )


def _classify_regulatory(title: str, item: NewsItem) -> Optional[HCEvent]:
    # CRL first — a Complete Response Letter is unambiguous and distinct from
    # an approval; it must never be mis-read as one.
    if _CRL.search(title):
        return _build(item, CRL, DIR_NA)
    # Approval + clearance share the same suppression gate: pending milestone,
    # denial/rejection (F2), or third-party commentary (F3). Clearance was
    # previously ungated (F1).
    if _reg_suppressed(title):
        return None
    if _APPROVAL.search(title):
        return _build(item, FDA_APPROVAL, DIR_NA)
    if _CLEARANCE.search(title):
        return _build(item, CLEARANCE, DIR_NA)
    return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def _build(item: NewsItem, event_type: str, direction: str,
           *, phase: str = "") -> HCEvent:
    return HCEvent(
        news_id=item.news_id,
        symbol="",  # attribution decided by the emit path (tickers ∩ universe)
        event_type=event_type,
        direction=direction,
        headline=item.title,
        source=item.source,
        url=item.url,
        published_at=item.published_at,
        phase=phase,
        confidence="high",
        raw_industries=tuple(item.industries),
    )


def classify(item: NewsItem) -> Optional[HCEvent]:
    """Classify a NewsItem into an HCEvent, or None if it isn't one.

    Precision-biased: returns None on any ambiguity. Regulatory actions
    (approval / CRL / clearance) are checked before trial readouts — an
    approval PR carries no Phase grammar, so the two families don't collide.
    """
    title = item.title or ""
    if not title.strip():
        return None

    reg = _classify_regulatory(title, item)
    if reg is not None:
        return reg

    return _classify_trial(title, item)
