"""Tests for §7 Follow-up detection + emission (_emit_followups + delivery gate).

Covers the correctness-sensitive lifecycle rules:
- a follow-up fires ONLY for a halt sa-monitor actually DELIVERED an alert for
  (emitted_halts), not one merely observed (seen_halts)
- non-emit reason code (never alerted)      → no follow-up  (Bug 1)
- live post_halt that failed (never posted)  → no follow-up  (Bug 2)
- resolving PR already cached at halt time    → cross-ref note, NO duplicate
  standalone follow-up                                        (Bug 3)
- resolving PR that arrives in a LATER poll   → STILL fires a follow-up
- one follow-up per halt, ever; no-match → nothing; dry-run posts+marks nothing
"""
from datetime import datetime, timezone
from unittest.mock import patch

from src.coverage import TickerMeta
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent
from src.halt_monitor import RunStats, _emit, _emit_followups
from src.news.cache import NewsCache
from src.news.types import NewsItem


class StubUniverse:
    """Minimal Universe stand-in — _emit / _emit_followups only call .get()."""

    def __init__(self, mapping):
        self._m = {k.upper(): v for k, v in mapping.items()}

    def get(self, symbol):
        return self._m.get(symbol.upper())


def _halt(symbol="VRDN", reason_code="T1"):
    # 07:00 ET on 2026-05-05 (EDT) == 11:00 UTC.
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date="2026-05-05",
        halt_time="07:00:00", reason_code=reason_code,
        reason_description="News Pending", name="Viridian Therapeutics",
        last_price=14.06, source="nasdaq_rss",
    )


def _meta(symbol="VRDN"):
    return TickerMeta(symbol=symbol, name="Viridian Therapeutics Inc",
                      sector="Biopharma", subsector="Biotech")


def _post_halt_pr_cache(pub="2026-05-05T11:10:00+00:00", symbol="VRDN",
                        title="Viridian reports positive Phase 3 topline"):
    cache = NewsCache()
    now = datetime(2026, 5, 5, 11, 40, tzinfo=timezone.utc)
    cache.ingest([NewsItem(
        source="prnewswire", title=title, body="b",
        url=f"https://prn.test/{symbol}", published_at=pub, tickers=(symbol,),
    )], now_utc=now)
    return cache


def _deliver_halt(tracker, event, universe, cache, *, slack_mode="off",
                  include_non_emit=False, stats=None):
    """Run the REAL halt-delivery path (tracker.ingest → _emit) so emitted_halts
    is populated with production's exact delivery semantics."""
    stats = stats or RunStats(started_at="t")
    for kind, ev in tracker.ingest([event]):
        _emit(kind, ev, universe, None, include_non_emit=include_non_emit,
              stats=stats, slack_mode=slack_mode, news_cache=cache, tracker=tracker)
    return stats


def _run_followups(tracker, universe, cache, *, slack_mode="off"):
    stats = RunStats(started_at="t")
    _emit_followups(tracker, universe, cache, None,
                    stats=stats, slack_mode=slack_mode)
    return stats


def test_delivered_covered_halt_then_later_pr_emits_followup(capsys):
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())  # delivered, no PR yet
    assert halt.halt_id in tracker.emitted_halts

    stats = _run_followups(tracker, universe, _post_halt_pr_cache())
    assert stats.followups_emitted == 1
    assert halt.halt_id in tracker.followed_up
    out = capsys.readouterr().out
    assert "Follow-up: Viridian reports positive Phase 3 topline" in out
    assert "Follows the 07:00 ET halt on VRDN" in out


def test_one_followup_per_halt_ever():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())
    cache = _post_halt_pr_cache()

    first = _run_followups(tracker, universe, cache)
    second = _run_followups(tracker, universe, cache)  # same state, PR still cached
    assert first.followups_emitted == 1
    assert second.followups_emitted == 0
    assert len(tracker.followed_up) == 1


def test_no_match_no_emit():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())
    # PR crossed BEFORE the halt — the cross-ref-note case, not a follow-up.
    cache = NewsCache()
    cache.ingest([NewsItem(
        source="prnewswire", title="pre-halt PR", body="b",
        url="https://prn.test/pre", published_at="2026-05-05T10:50:00+00:00",
        tickers=("VRDN",),
    )], now_utc=datetime(2026, 5, 5, 11, 0, tzinfo=timezone.utc))

    stats = _run_followups(tracker, universe, cache)
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()


# --- Bug 1: non-emit reason code (never alerted) → no follow-up -------------
def test_non_emit_reason_code_halt_no_followup():
    halt = _halt(reason_code="O1")  # Operations Halt — excluded by default
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())  # skipped by non-emit filter
    assert halt.halt_id in tracker.seen_halts          # observed
    assert halt.halt_id not in tracker.emitted_halts   # but NOT delivered

    stats = _run_followups(tracker, universe, _post_halt_pr_cache())
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()


# --- Bug 2: live post_halt failed (never posted) → no follow-up -------------
@patch("src.slack.post_halt", side_effect=RuntimeError("slack down"))
def test_failed_live_post_halt_no_followup(_mock_post):
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache(), slack_mode="live")
    # Fix #1: a failed LIVE post drops the halt from seen_halts so the next poll
    # retries it — so it is neither seen nor delivered (previously it stuck in
    # seen_halts, silently lost forever).
    assert halt.halt_id not in tracker.seen_halts
    assert halt.halt_id not in tracker.emitted_halts  # post raised → not delivered

    stats = _run_followups(tracker, universe, _post_halt_pr_cache())
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()


# --- Bug 3: PR cached at halt time → cross-ref note, NO duplicate follow-up --
def test_pr_at_halt_time_yields_note_not_duplicate_followup(capsys):
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    # PR coincident with the halt instant (11:00:00Z), cached BEFORE delivery.
    cache = _post_halt_pr_cache(pub="2026-05-05T11:00:00+00:00")
    _deliver_halt(tracker, halt, universe, cache)

    out = capsys.readouterr().out
    assert "Follows PR Newswire press release" in out  # halt's cross-ref note
    assert halt.halt_id in tracker.emitted_halts
    assert halt.halt_id in tracker.followed_up  # pre-marked → suppresses standalone

    stats = _run_followups(tracker, universe, cache)
    assert stats.followups_emitted == 0  # no duplicate


def test_pr_just_outside_note_window_still_fires_followup_same_poll(capsys):
    """Codex round-2 regression. A PR cached at halt-delivery time but OUTSIDE
    the note's +5min window (here +10min) is NOT referenced by the halt's
    cross-ref note, so it must NOT be pre-marked — it still fires a real
    follow-up in the same poll. Guards against the earlier bug where the
    pre-mark used find_followup_news's wider 60min window and silently dropped
    the news from BOTH the note and the follow-up.
    Note window = [halt-60m, halt+5m]; follow-up window = [halt, halt+60m]."""
    halt = _halt()  # 11:00:00Z (07:00 ET)
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    # PR 10 min after the halt: outside the note (+5m), inside the follow-up
    # (+60m), and cached BEFORE delivery (same poll).
    cache = _post_halt_pr_cache(pub="2026-05-05T11:10:00+00:00")
    _deliver_halt(tracker, halt, universe, cache)

    out = capsys.readouterr().out
    assert "Follows PR Newswire press release" not in out  # note did NOT fire
    assert halt.halt_id in tracker.emitted_halts
    assert halt.halt_id not in tracker.followed_up  # NOT pre-marked

    stats = _run_followups(tracker, universe, cache)
    assert stats.followups_emitted == 1  # follow-up delivers the news


# --- The complement: PR that lands in a LATER poll STILL fires --------------
def test_pr_in_later_poll_still_fires_followup():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())  # empty cache at delivery
    assert halt.halt_id not in tracker.followed_up  # not pre-marked

    stats = _run_followups(tracker, universe, _post_halt_pr_cache())  # PR now present
    assert stats.followups_emitted == 1
    assert halt.halt_id in tracker.followed_up


def test_uncovered_halt_never_delivered_or_followed_up():
    halt = _halt(symbol="ZZZZ")
    universe = StubUniverse({})  # ZZZZ not covered
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())
    assert halt.halt_id not in tracker.emitted_halts

    stats = _run_followups(tracker, universe, _post_halt_pr_cache(symbol="ZZZZ"))
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()


def test_dry_run_followup_posts_nothing_and_marks_nothing():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())
    stats = _run_followups(tracker, universe, _post_halt_pr_cache(), slack_mode="dry-run")
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()  # re-testable — no mark in dry-run


def test_no_news_cache_is_noop():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    _deliver_halt(tracker, halt, universe, NewsCache())
    stats = _run_followups(tracker, universe, None)
    assert stats.followups_emitted == 0
    assert tracker.followed_up == set()
