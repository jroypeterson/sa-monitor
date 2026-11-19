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


# --- Finding 1 (2026-11-18): Nasdaq relabels a resumed row to T3 -------------

def _relabelled(code, resume_trade_time="07:30:00"):
    return HaltEvent(
        symbol="VRDN", exchange="Nasdaq", halt_date="2026-05-05",
        halt_time="07:00:00", reason_code=code, reason_description="",
        name="Viridian Therapeutics", source="nasdaq_rss",
        resume_trade_time=resume_trade_time,
    )


def test_t3_resume_of_delivered_halt_is_posted_once():
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    with patch("src.slack.post_halt"):
        _poll(tracker, [_halt()], universe, stats)
    assert _halt().halt_id in tracker.emitted_halts

    with patch("src.slack.post_resume") as post:
        _poll(tracker, [_relabelled("T3")], universe, stats)
        _poll(tracker, [_relabelled("T3")], universe, stats)  # repeat poll
    assert post.call_count == 1


def test_deletion_code_d_is_never_posted_as_resume():
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    with patch("src.slack.post_halt"):
        _poll(tracker, [_halt()], universe, stats)

    with patch("src.slack.post_resume") as post:
        _poll(tracker, [_relabelled("D")], universe, stats)
    assert post.call_count == 0


def test_t3_resume_of_undelivered_halt_is_not_posted():
    """A resume is sent iff its halt was delivered: a halt seen only as T3 was
    never delivered, so its T3 resume stays filtered."""
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    with patch("src.slack.post_halt") as post_halt, \
            patch("src.slack.post_resume") as post_resume:
        _poll(tracker, [_relabelled("T3")], universe, stats)
    assert post_halt.call_count == 0
    assert post_resume.call_count == 0


def test_same_batch_t3_then_t1_delivers_halt_and_t1_resume():
    """End to end through _emit: Nasdaq T3+resume first, NYSE T1+resume second,
    in one poll. Both the halt and the resume are delivered exactly once."""
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    nyse_t1 = HaltEvent(
        symbol="VRDN", exchange="NYSE", halt_date="2026-05-05",
        halt_time="07:00:00", reason_code="T1", reason_description="News Pending",
        name="Viridian Therapeutics", source="nyse_csv",
        resume_trade_time="07:30:00",
    )
    with patch("src.slack.post_halt") as post_halt, \
            patch("src.slack.post_resume") as post_resume:
        _poll(tracker, [_relabelled("T3"), nyse_t1], universe, stats)
        _poll(tracker, [_relabelled("T3"), nyse_t1], universe, stats)
    assert post_halt.call_count == 1
    assert post_resume.call_count == 1


# --- Finding 6 (2026-11-18): a failed state save must not leave the run green -

def test_failed_state_save_is_counted_and_fails_exit():
    from src import halt_monitor
    stats = RunStats(started_at="t")
    tracker = HaltTracker()
    with patch("src.state.save", side_effect=OSError("disk full")):
        halt_monitor._save_state(tracker, stats)
    assert stats.state_save_failures == 1
    assert stats.state_last_save_ok is False
    assert halt_monitor.exit_code_for(stats, persist_state=True) == 1


def test_recovered_state_save_exits_zero_but_keeps_count():
    from src import halt_monitor
    stats = RunStats(started_at="t")
    tracker = HaltTracker()
    with patch("src.state.save", side_effect=OSError("disk full")):
        halt_monitor._save_state(tracker, stats)
    with patch("src.state.save"):
        halt_monitor._save_state(tracker, stats)
    assert stats.state_save_failures == 1
    assert halt_monitor.exit_code_for(stats, persist_state=True) == 0


def test_failed_state_save_escalates_heartbeat():
    from src import halt_monitor
    stats = RunStats(started_at="t", state_save_failures=2, state_last_save_ok=False)
    with patch("src.slack.post_dm") as dm:
        halt_monitor._post_health_heartbeat(stats, "live")
    summary = dm.call_args.args[0]
    assert "state_save_failures=2" in summary
    assert dm.call_args.kwargs["level"] == "warning"


def test_main_returns_1_when_last_save_failed():
    from src import halt_monitor
    failed = RunStats(started_at="t", state_save_failures=1, state_last_save_ok=False)
    with patch("src.halt_monitor.run", return_value=failed):
        assert halt_monitor.main(["--once", "--log", "unused.jsonl"]) == 1
    ok = RunStats(started_at="t")
    with patch("src.halt_monitor.run", return_value=ok):
        assert halt_monitor.main(["--once", "--log", "unused.jsonl"]) == 0


def test_resume_waits_when_its_halt_post_failed_same_poll():
    """Codex R1: halt + resume in one poll, halt post fails. The resume must not
    be posted for an undelivered halt; both retry next poll, once each."""
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    resumed = _halt(resume_trade_time="07:30:00")
    with patch("src.slack.post_halt", side_effect=RuntimeError("slack down")),             patch("src.slack.post_resume") as post_resume:
        _poll(tracker, [resumed], universe, stats)
    assert post_resume.call_count == 0
    assert resumed.halt_id not in tracker.resumes_emitted

    with patch("src.slack.post_halt") as post_halt,             patch("src.slack.post_resume") as post_resume:
        _poll(tracker, [resumed], universe, stats)
        _poll(tracker, [resumed], universe, stats)
    assert post_halt.call_count == 1
    assert post_resume.call_count == 1
    assert resumed.halt_id in tracker.resumes_delivered


def test_upgraded_resume_waits_when_upgraded_halt_post_failed():
    """Codex R1 repro: [T3+resume, T1+resume] in one poll, post_halt fails,
    post_resume would succeed -> no orphan resume; next poll delivers both."""
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    nyse_t1 = HaltEvent(
        symbol="VRDN", exchange="NYSE", halt_date="2026-05-05",
        halt_time="07:00:00", reason_code="T1", reason_description="News Pending",
        name="Viridian Therapeutics", source="nyse_csv",
        resume_trade_time="07:30:00",
    )
    batch = [_relabelled("T3"), nyse_t1]
    with patch("src.slack.post_halt", side_effect=RuntimeError("slack down")),             patch("src.slack.post_resume") as post_resume:
        _poll(tracker, batch, universe, stats)
    assert post_resume.call_count == 0

    with patch("src.slack.post_halt") as post_halt,             patch("src.slack.post_resume") as post_resume:
        _poll(tracker, batch, universe, stats)
        _poll(tracker, batch, universe, stats)
    assert post_halt.call_count == 1
    assert post_resume.call_count == 1


def test_filtered_resume_is_not_in_delivered_ledger():
    universe = StubUniverse({"VRDN": _meta()})
    tracker = HaltTracker()
    stats = RunStats(started_at="t")
    with patch("src.slack.post_halt"):
        _poll(tracker, [_halt()], universe, stats)
    with patch("src.slack.post_resume"):
        _poll(tracker, [_relabelled("D")], universe, stats)
    assert _halt().halt_id in tracker.resumes_emitted
    assert _halt().halt_id not in tracker.resumes_delivered
