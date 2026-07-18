"""Fix #1: a transient LIVE Slack post failure must not permanently drop an
event. tracker.ingest() records the dedup marker BEFORE the post attempt, so on
a failed live post _emit rolls the marker back and the next poll retries.
"""
from unittest.mock import patch

from src.coverage import TickerMeta
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent
from src.halt_monitor import RunStats, _emit


class StubUniverse:
    def __init__(self, mapping):
        self._m = {k.upper(): v for k, v in mapping.items()}

    def get(self, symbol):
        return self._m.get(symbol.upper())


def _halt(resume_trade_time=None):
    return HaltEvent(
        symbol="VRDN", exchange="Nasdaq", halt_date="2026-05-05",
        halt_time="07:00:00", reason_code="T1", reason_description="News Pending",
        name="Viridian Therapeutics", source="nasdaq_rss",
        resume_trade_time=resume_trade_time,
    )


def _meta():
    return TickerMeta(symbol="VRDN", name="Viridian Therapeutics Inc",
                      sector="Biopharma", subsector="Biotech")


def _poll(tracker, events, universe, stats, **kw):
    for kind, ev in tracker.ingest(events):
        _emit(kind, ev, universe, None, include_non_emit=False, stats=stats,
              slack_mode="live", tracker=tracker, **kw)


def test_failed_live_halt_post_retries_next_poll():
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")

    # Poll 1: the live post raises. Marker must be rolled back for retry.
    with patch("src.slack.post_halt", side_effect=RuntimeError("slack down")):
        _poll(tracker, [halt], universe, stats)
    assert halt.halt_id not in tracker.seen_halts       # dropped for retry
    assert halt.halt_id not in tracker.emitted_halts     # never delivered
    assert stats.slack_posts_failed == 1

    # Delivery-accurate render counter: the failed poll rolled it back, so it
    # must NOT count the undelivered halt.
    assert stats.halts_emitted == 0

    # Poll 2: the SAME halt is re-fetched from the feed; post now succeeds.
    with patch("src.slack.post_halt") as ok_post:
        _poll(tracker, [halt], universe, stats)
        assert ok_post.called                             # actually retried + posted
    assert halt.halt_id in tracker.seen_halts
    assert halt.halt_id in tracker.emitted_halts
    assert stats.slack_posts_succeeded == 1
    # The eventual single delivery is counted exactly once (no double-count from
    # the failed-then-retried poll).
    assert stats.halts_emitted == 1


def test_failed_live_resume_post_retries_next_poll():
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")

    # Poll 1: deliver the halt cleanly (no resume yet).
    with patch("src.slack.post_halt"):
        _poll(tracker, [_halt()], universe, stats)
    assert _halt().halt_id in tracker.emitted_halts

    resumed = _halt(resume_trade_time="07:30:00")
    # Poll 2: resume now published, but the resume post fails → roll back.
    with patch("src.slack.post_resume", side_effect=RuntimeError("slack down")):
        _poll(tracker, [resumed], universe, stats)
    assert resumed.halt_id not in tracker.resumes_emitted   # rolled back for retry
    assert stats.resumes_emitted == 0                        # undelivered → not counted

    # Poll 3: same resumed event, post succeeds → resume delivered once.
    with patch("src.slack.post_resume") as ok_resume:
        _poll(tracker, [resumed], universe, stats)
        assert ok_resume.called
    assert resumed.halt_id in tracker.resumes_emitted
    assert stats.resumes_emitted == 1                        # counted exactly once


def test_successful_live_post_keeps_marker():
    """Control: a clean live post leaves the halt in seen_halts + emitted_halts."""
    halt = _halt()
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    with patch("src.slack.post_halt"):
        _poll(tracker, [halt], universe, stats)
    assert halt.halt_id in tracker.seen_halts
    assert halt.halt_id in tracker.emitted_halts
    # A repeat poll does NOT re-post (already seen).
    with patch("src.slack.post_halt") as p:
        _poll(tracker, [halt], universe, stats)
        assert not p.called
