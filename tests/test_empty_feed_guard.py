"""Empty-feed guard: a full session with zero market-wide events on both
exchange feeds must read as `warning`, never a bare `ok · halts=0`
(HEALTH_REPORTING.md §4.2 abnormal-counts rule)."""
from src.halt_monitor import (
    EMPTY_FEED_MIN_POLLS,
    RunStats,
    _empty_feed_suspect,
)


def _stats(**kw) -> RunStats:
    s = RunStats(started_at="t")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_full_session_zero_events_is_suspect():
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=0, nyse_events_seen=0)
    assert _empty_feed_suspect(s, ended_with_error=False)


def test_quiet_but_nonzero_market_not_suspect():
    """A day with any market-wide events (even none in-universe) is a real
    quiet day, not a broken feed — `halts=0` alone must NOT warn."""
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=37, nyse_events_seen=12, halts_emitted=0)
    assert not _empty_feed_suspect(s, ended_with_error=False)


def test_one_live_feed_not_suspect():
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=0, nyse_events_seen=3)
    assert not _empty_feed_suspect(s, ended_with_error=False)


def test_short_session_skipped():
    """A cut-short run can't judge feed emptiness — no false warning."""
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS - 1,
               nasdaq_events_seen=0, nyse_events_seen=0)
    assert not _empty_feed_suspect(s, ended_with_error=False)


def test_errored_run_not_double_flagged():
    """An `error` run already alarms; the feed guard stays out of the way."""
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=0, nyse_events_seen=0)
    assert not _empty_feed_suspect(s, ended_with_error=True)


def test_heartbeat_downgrades_and_explains(monkeypatch):
    """End-to-end through _post_health_heartbeat: suspect session posts
    level=warning with the events_seen counter + explanatory note."""
    import src.halt_monitor as hm

    posted = {}

    def fake_post_dm(summary, level="ok"):
        posted["summary"], posted["level"] = summary, level

    monkeypatch.setattr(hm.slack, "post_dm", fake_post_dm)
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=0, nyse_events_seen=0)
    hm._post_health_heartbeat(s, slack_mode="live", ended_with_error=False)
    assert posted["level"] == "warning"
    assert "events_seen=0/0" in posted["summary"]
    assert "zero market-wide events" in posted["summary"]


def test_heartbeat_healthy_session_stays_ok(monkeypatch):
    import src.halt_monitor as hm

    posted = {}

    def fake_post_dm(summary, level="ok"):
        posted["summary"], posted["level"] = summary, level

    monkeypatch.setattr(hm.slack, "post_dm", fake_post_dm)
    s = _stats(polls_completed=EMPTY_FEED_MIN_POLLS,
               nasdaq_events_seen=41, nyse_events_seen=9)
    hm._post_health_heartbeat(s, slack_mode="live", ended_with_error=False)
    assert posted["level"] == "ok"
    assert "events_seen=41/9" in posted["summary"]
