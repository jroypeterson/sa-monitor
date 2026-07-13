"""Tests for the HC event-wire lane — classify() + _emit_hc_events.

Two halves:

1. classify() precision — a POSITIVE set anchored to the locked real headlines
   in template-library.md §15/§16/§19, and a NEGATIVE set of headlines that
   must NOT fire (presentations, trial initiation/enrollment, earnings/
   financing/personnel PRs, pending FDA milestones, boilerplate "FDA-cleared").
   A wrong "Phase 3 met" / "FDA approval" alert is worse than a miss, so the
   NEGATIVE set is the load-bearing guard.

2. _emit_hc_events lifecycle — detection, covered-only filter, dedup, and the
   slack-mode delivery gate (off marks, live marks only on post success,
   dry-run marks nothing), mirroring tests/test_followup.py.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src import state
from src.coverage import TickerMeta
from src.dedup import HaltTracker
from src.events.classify import classify
from src.events.types import (
    CLEARANCE,
    CRL,
    DIR_MET,
    DIR_MISSED,
    DIR_NA,
    FDA_APPROVAL,
    TRIAL_READOUT,
)
from src.halt_monitor import RunStats, _emit_hc_events
from src.news.types import NewsItem


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

class StubUniverse:
    """Minimal Universe stand-in — _emit_hc_events only calls .get()."""

    def __init__(self, mapping):
        self._m = {k.upper(): v for k, v in mapping.items()}

    def get(self, symbol):
        return self._m.get(symbol.upper())


def _meta(symbol="VRDN", subsector="Biotech"):
    return TickerMeta(symbol=symbol, name=f"{symbol} Inc",
                      sector="Biopharma", subsector=subsector)


def _item(title, *, tickers=("VRDN",), source="prnewswire",
          url=None, pub="2026-05-05T11:05:00+00:00"):
    return NewsItem(
        source=source, title=title, body="body text",
        url=url or f"https://prn.test/{abs(hash(title)) % 10**8}",
        published_at=pub, tickers=tickers,
    )


# --------------------------------------------------------------------------
# 1a. classify() — POSITIVE set (anchored to §15 / §16 / §19)
# --------------------------------------------------------------------------

POSITIVE = [
    # (title, event_type, direction, phase)
    # §16 FDA approval — issuer-press-release variant (ARVN 2026-05-01 real capture)
    ("Arvinas issues press release on FDA approval of VEPPANU (vepdegestrant) "
     "for the treatment of ESR1M, ER+/HER2- advanced breast cancer",
     FDA_APPROVAL, DIR_NA, ""),
    # §16 FDA approval — headline variant
    ("FDA approves Veppanu for ESR1M, ER+/HER2- advanced breast cancer",
     FDA_APPROVAL, DIR_NA, ""),
    ("Acme Pharma Receives FDA Approval for Acmezumab in metastatic melanoma",
     FDA_APPROVAL, DIR_NA, ""),
    ("FDA grants accelerated approval of Novadrug for rare genetic disorder",
     FDA_APPROVAL, DIR_NA, ""),
    # §19 trial readout — MET (VRDN 2026-05-05 real capture)
    ("Viridian reports Phase 3 REVEAL-2 trial of elegrobart in chronic thyroid "
     "eye disease met its primary endpoint",
     TRIAL_READOUT, DIR_MET, "3"),
    # §19 met dual primary
    ("Cytokinetics reports ACACIA-HCM Phase 3 met dual primary endpoints",
     TRIAL_READOUT, DIR_MET, "3"),
    ("Newco achieves primary endpoint in Phase 2 study of newzumab",
     TRIAL_READOUT, DIR_MET, "2"),
    # §15 trial readout — MISSED (DAZALS / CEDAR real phrasings)
    ("Corcept reports Phase 2 DAZALS study of dazucorilant does not meet "
     "primary endpoint",
     TRIAL_READOUT, DIR_MISSED, "2"),
    ("Bigco reports Phase 2B CEDAR study of drugx did not meet its primary or "
     "secondary efficacy endpoints",
     TRIAL_READOUT, DIR_MISSED, "2"),
    ("Smallco announces Phase 3 pivotal trial failed to meet primary endpoint",
     TRIAL_READOUT, DIR_MISSED, "3"),
    # topline, direction TBD (still a genuine readout crossing)
    ("Genco announces topline results from Phase 3 SUNRISE trial of gencept",
     TRIAL_READOUT, DIR_NA, "3"),
    # CRL
    ("Regenco receives Complete Response Letter from FDA for regzumab",
     CRL, DIR_NA, ""),
    # medtech clearance
    ("Deviceco receives FDA clearance for its AI-powered cardiac monitor",
     CLEARANCE, DIR_NA, ""),
    ("Deviceco announces FDA 510(k) clearance of its next-gen catheter",
     CLEARANCE, DIR_NA, ""),
    # F5: idiomatic CRL still fires (only the BARE-token/ticker collision is fixed)
    ("FDA issues CRL for acmezumab citing manufacturing deficiencies",
     CRL, DIR_NA, ""),
    ("Acme receives a CRL from the FDA for acmezumab",
     CRL, DIR_NA, ""),
    # F4 guard: a real MET readout that merely contains the word "expected"
    # (not a future timeline) must STILL fire
    ("Acme reports Phase 3 trial met primary endpoint, better than expected",
     TRIAL_READOUT, DIR_MET, "3"),
    # round-2 #4: designation words must NOT veto a clear approval verb
    ("FDA approves acmezumab under Priority Review for advanced disease",
     FDA_APPROVAL, DIR_NA, ""),
    ("Acme receives FDA approval of acmezumab, previously granted Breakthrough "
     "Therapy designation",
     FDA_APPROVAL, DIR_NA, ""),
    # round-2 #2 guard: an approval that merely contains a future word still fires
    ("FDA approves acmezumab sooner than expected, ahead of schedule",
     FDA_APPROVAL, DIR_NA, ""),
    # round-2 #3 guard: "announces" is not commentary
    ("Acme announces FDA approval of acmezumab for advanced disease",
     FDA_APPROVAL, DIR_NA, ""),
    # round-2 #2 guard: a real clearance still fires
    ("Acme receives FDA clearance for its next-gen cardiac monitor",
     CLEARANCE, DIR_NA, ""),

    # --- Codex round-3 fixes: false-negatives that must now FIRE -------------
    # FN-A: the STANDARD readout PR — explicit met/missed + a co-mentioned call
    ("Acme Announces Phase 3 Trial Met Primary Endpoint; Conference Call Today "
     "at 8am ET", TRIAL_READOUT, DIR_MET, "3"),
    ("Acme reports Phase 3 study did not meet primary endpoint; webcast to "
     "discuss results today", TRIAL_READOUT, DIR_MISSED, "3"),
    # FN-B: COMPLETED FDA grants that co-mention procedural nouns
    ("FDA approves supplemental application for acmezumab in expanded indication",
     FDA_APPROVAL, DIR_NA, ""),
    ("FDA clears 510(k) premarket notification for Acme's cardiac monitor",
     CLEARANCE, DIR_NA, ""),
    # FN-C: self-approval with an ambiguous verb now fires (announce guard too)
    ("Acme highlights FDA approval of its drug acmezumab for advanced disease",
     FDA_APPROVAL, DIR_NA, ""),
    ("Acme announces FDA approval of acmezumab for advanced disease",
     FDA_APPROVAL, DIR_NA, ""),
]


@pytest.mark.parametrize("title,etype,direction,phase", POSITIVE)
def test_classify_positive(title, etype, direction, phase):
    ev = classify(_item(title))
    assert ev is not None, f"expected an event, got None for: {title}"
    assert ev.event_type == etype
    assert ev.direction == direction
    assert ev.phase == phase
    assert ev.headline == title          # verbatim
    assert ev.symbol == ""               # attribution decided in the emit path
    assert ev.confidence == "high"


# --------------------------------------------------------------------------
# 1b. classify() — NEGATIVE set (must ALL return None)
# --------------------------------------------------------------------------

NEGATIVE = [
    # presentations / future data disclosure (not a readout)
    "Acme to present Phase 3 REVEAL data at the ASCO 2026 annual conference",
    "Acme will present detailed Phase 2 results at an upcoming medical congress",
    "Acme presents Phase 3 topline data in a late-breaking poster presentation",
    "Acme to present topline Phase 2 data next week",
    # trial lifecycle, not a readout
    "Acme announces initiation of Phase 3 pivotal trial of acmezumab",
    "Acme doses first patient in Phase 3 study of acmezumab",
    "Acme completes enrollment in Phase 3 ELEVATE trial",
    "Acme to host conference call to discuss Phase 3 trial design",
    "Acme enrolls first patient in Phase 2 basket trial",
    # non-clinical PRs (no readout, no approval)
    "Acme reports first quarter 2026 financial results",
    "Acme announces $150 million underwritten public offering",
    "Acme appoints Jane Doe as Chief Executive Officer",
    "Acme to participate in the Phase Capital healthcare investor conference",
    # pending / procedural FDA milestones (NOT an approval)
    "FDA accepts Acme's New Drug Application for acmezumab",
    "FDA grants Priority Review to Acme's application for acmezumab",
    "FDA grants Fast Track designation to acmezumab",
    "FDA grants Breakthrough Therapy designation for acmezumab",
    "Acme submits Biologics License Application to FDA seeking approval of acmezumab",
    "Acme resubmits application for FDA approval of acmezumab following prior review",
    # boilerplate adjective — must NOT read as a clearance event
    "Acme opens new FDA-cleared manufacturing facility in North Carolina",
    # ambiguous secondary-only readout — precision says skip
    "Acme reports Phase 2 study met key secondary endpoint",

    # --- Codex round-1 repros ------------------------------------------------
    # F1: clearance path was UNGATED — pending / denial framings must not fire
    "Acme submits 510(k) for FDA clearance of its cardiac monitor",
    "Acme did not receive FDA clearance for its cardiac monitor",
    "Acme fails to receive FDA clearance for its device",
    "FDA denies 510(k) clearance for Acme's device",
    "Acme withdraws 510(k) clearance application for its device",
    # F2: negative-approval INVERSION — a rejection must never read as approval
    "Acme did not receive FDA approval for acmezumab",
    "Acme fails to win FDA approval for acmezumab",
    "FDA rejects Acme's application; acmezumab not approved",
    "Acme's acmezumab did not win FDA approval this cycle",
    # F3: competitor / commentary approval attribution
    "Acme comments on FDA approval of RivalDrug by a competitor",
    "Acme issues statement on FDA approval of a rival therapy",
    "Acme congratulates partner on FDA approval of RivalDrug",
    # F4: future 'expected in' topline (adjectival, not caught by 'expects to')
    "Acme announces topline Phase 3 data expected in Q4 2026",
    "Acme Phase 3 SUNRISE topline readout expected in the second half of 2026",
    "Acme on track to read out Phase 3 data later this year",
    # F5: bare CRL collides with Charles River Labs (ticker CRL, covered)
    "CRL Announces First-Quarter 2026 Financial Results",
    "Charles River Laboratories (CRL) Announces New Facility in Massachusetts",

    # --- Codex round-2 repros ------------------------------------------------
    # #2: clearance pending / intent / future framings must not fire
    "Acme targets FDA clearance in Q4 2026",
    "Acme expects FDA clearance for its cardiac monitor",
    "Acme's device remains pending FDA clearance",
    "FDA clearance expected in Q4 2026 for Acme's monitor",
    "Acme seeks FDA clearance for its next-gen catheter",
    # (round-2 #3 highlights/notes/discusses cases were REMOVED in round-3 FN-C:
    #  those verbs also suppressed self-approvals, so they now FIRE — see the
    #  round-3 positive/regression tests below.)
    # #1: more future-readout phrasings
    "Acme to report topline Phase 3 data in Q4 2026",
    "Acme expects to report topline Phase 3 SUNRISE results next year",
    "Acme Phase 3 topline data anticipated in H2 2026",
    "Topline data from Acme's Phase 3 trial to be reported in 2027",

    # --- Codex round-3 repros: still-suppressed (no regression) --------------
    # FN-A: topline WITHOUT an explicit met/missed result is still vetoed by
    # future/presentation framing
    "Acme Phase 3 topline data to be presented at ASCO 2026",
    "Acme announces topline Phase 3 data expected in Q4 2026 outlook",
    # FN-B: pending-application framings still None (the narrowed pending gate +
    # verb-anchoring keep these out)
    "FDA accepts Acme's NDA for acmezumab",
    "FDA grants Priority Review to acmezumab",
    "Acme submits BLA to FDA seeking approval of acmezumab",
    "Acme files for FDA approval of acmezumab",
    # FN-C: CLEAR third-party commentary still suppressed
    "Acme comments on FDA approval of a rival therapy",
]


@pytest.mark.parametrize("title", NEGATIVE)
def test_classify_negative(title):
    assert classify(_item(title)) is None, f"MISFIRE: {title!r} should not classify"


def test_classify_blank_title_is_none():
    assert classify(_item("   ")) is None


# --------------------------------------------------------------------------
# F6 — biotech CTA wording: HC events must NOT say "Biotech halt"
# --------------------------------------------------------------------------

def test_hc_event_cta_does_not_say_halt(capsys):
    from src import slack
    from dataclasses import replace
    item = _item("Viridian reports Phase 3 REVEAL-2 met its primary endpoint",
                 tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()
    _run_emit([item], universe, tracker)
    out = capsys.readouterr().out
    assert "Biotech readout" in out            # event-appropriate wording
    assert "Biotech halt" not in out           # F6: not the halt wording

    # Slack block carries the same corrected wording.
    ev = replace(classify(item), symbol="VRDN")
    blocks = slack.build_hc_event_blocks(ev, _meta("VRDN"))
    text = blocks["blocks"][0]["text"]["text"]
    assert "Biotech readout" in text and "Biotech halt" not in text


def test_biotech_triage_cta_halt_wording_unchanged():
    """The halt/resume path must still read 'Biotech halt' (default context)."""
    from src.template import biotech_triage_cta
    assert biotech_triage_cta("VRDN") == \
        ":dna: Biotech halt — triage this name?  ->  `triage VRDN`"
    assert biotech_triage_cta("VRDN", context="approval").startswith(
        ":dna: Biotech approval —")


# --------------------------------------------------------------------------
# 2. _emit_hc_events — lifecycle / gating
# --------------------------------------------------------------------------

def _run_emit(news_items, universe, tracker, *, slack_mode="off"):
    stats = RunStats(started_at="t")
    _emit_hc_events(news_items, universe, tracker, None,
                    stats=stats, slack_mode=slack_mode)
    return stats


def test_covered_readout_emits_and_renders(capsys):
    item = _item("Viridian reports Phase 3 REVEAL-2 trial of elegrobart in "
                 "chronic thyroid eye disease met its primary endpoint",
                 tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 1
    key = f"{item.news_id}|VRDN|{TRIAL_READOUT}"
    assert key in tracker.hc_events_emitted
    out = capsys.readouterr().out
    assert "VRDN" in out
    assert "met its primary endpoint" in out
    assert "[StreetAccount]" in out


def test_negative_item_emits_nothing(capsys):
    item = _item("Acme to present Phase 3 REVEAL data at the ASCO 2026 "
                 "annual conference", tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 0
    assert tracker.hc_events_emitted == set()
    assert capsys.readouterr().out.strip() == ""


def test_uncovered_ticker_never_fires():
    item = _item("FDA approves Zzzdrug for advanced disease", tickers=("ZZZZ",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})  # ZZZZ not covered
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 0
    assert tracker.hc_events_emitted == set()


def test_item_with_no_tickers_never_fires():
    item = _item("FDA approves Somedrug for advanced disease", tickers=())
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 0


def test_partner_ticker_covered_fires_for_partner():
    # Small biotech's approval names its covered large-pharma partner — both
    # tickers land in item.tickers; the covered one fires.
    item = _item("Arvinas issues press release on FDA approval of VEPPANU for "
                 "the treatment of ER+/HER2- advanced breast cancer",
                 tickers=("ARVN", "PFE"))
    universe = StubUniverse({"PFE": _meta("PFE", subsector="Pharma")})  # only PFE covered
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 1
    assert f"{item.news_id}|PFE|{FDA_APPROVAL}" in tracker.hc_events_emitted


def test_both_covered_tickers_each_fire_once():
    item = _item("Arvinas issues press release on FDA approval of VEPPANU",
                 tickers=("ARVN", "PFE"))
    universe = StubUniverse({"ARVN": _meta("ARVN"), "PFE": _meta("PFE")})
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker)
    assert stats.hc_events_emitted == 2
    assert f"{item.news_id}|ARVN|{FDA_APPROVAL}" in tracker.hc_events_emitted
    assert f"{item.news_id}|PFE|{FDA_APPROVAL}" in tracker.hc_events_emitted


def test_dedup_one_alert_per_pr_ticker_type_ever():
    item = _item("FDA approves Veppanu for advanced breast cancer", tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    first = _run_emit([item], universe, tracker)
    second = _run_emit([item], universe, tracker)  # same item re-fetched
    assert first.hc_events_emitted == 1
    assert second.hc_events_emitted == 0
    assert len(tracker.hc_events_emitted) == 1


def test_dry_run_renders_but_marks_nothing(capsys):
    item = _item("FDA approves Veppanu for advanced breast cancer", tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    stats = _run_emit([item], universe, tracker, slack_mode="dry-run")
    assert stats.hc_events_emitted == 0          # nothing delivered
    assert tracker.hc_events_emitted == set()    # re-testable — no mark
    assert "VRDN" in capsys.readouterr().out     # but it DID render


def test_live_post_failure_does_not_mark():
    item = _item("FDA approves Veppanu for advanced breast cancer", tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    with patch("src.slack.post_hc_event", side_effect=RuntimeError("slack down")):
        stats = _run_emit([item], universe, tracker, slack_mode="live")
    assert stats.hc_events_emitted == 0
    assert stats.slack_posts_failed == 1
    assert tracker.hc_events_emitted == set()   # post failed → not marked → retries next poll


def test_live_post_success_marks():
    item = _item("FDA approves Veppanu for advanced breast cancer", tickers=("VRDN",))
    universe = StubUniverse({"VRDN": _meta("VRDN")})
    tracker = HaltTracker()

    with patch("src.slack.post_hc_event", return_value={"ok": True}) as m:
        stats = _run_emit([item], universe, tracker, slack_mode="live")
    assert m.called
    assert stats.hc_events_emitted == 1
    assert f"{item.news_id}|VRDN|{FDA_APPROVAL}" in tracker.hc_events_emitted


# --------------------------------------------------------------------------
# 3. dedup / state round-trip for hc_events_emitted
# --------------------------------------------------------------------------

def test_reset_clears_hc_events():
    tracker = HaltTracker()
    tracker.hc_events_emitted.add("u|VRDN|fda_approval")
    tracker.reset()
    assert tracker.hc_events_emitted == set()


def test_hc_events_emitted_round_trip(tmp_path):
    tracker = HaltTracker()
    tracker.hc_events_emitted.add("https://prn.test/1|VRDN|trial_readout")
    tracker.hc_events_emitted.add("https://prn.test/2|ARVN|fda_approval")
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert fresh.hc_events_emitted == {
        "https://prn.test/1|VRDN|trial_readout",
        "https://prn.test/2|ARVN|fda_approval",
    }


def test_old_state_without_hc_field_rehydrates_empty(tmp_path):
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text(
        '{"schema_version": 1, "trading_day_et": "2026-05-05", '
        '"halts": [], "resumes_emitted": []}'
    )
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert fresh.hc_events_emitted == set()
