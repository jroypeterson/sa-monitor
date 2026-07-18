"""Tests for the HaltTracker dedup logic."""
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent


def make_event(symbol="VRDN", date="2026-05-05", time="06:55:32",
               resume_trade_time=None):
    return HaltEvent(
        symbol=symbol,
        exchange="Nasdaq",
        halt_date=date,
        halt_time=time,
        reason_code="T1",
        reason_description="News Pending",
        resume_trade_time=resume_trade_time,
        source="nasdaq_rss",
    )


def test_first_sighting_emits_halt():
    tracker = HaltTracker()
    event = make_event()
    out = list(tracker.ingest([event]))
    assert len(out) == 1
    assert out[0] == ("halt", event)


def test_repeat_poll_no_emit():
    tracker = HaltTracker()
    event = make_event()
    list(tracker.ingest([event]))  # first sighting
    out = list(tracker.ingest([event]))  # second sighting (same event re-fetched)
    assert out == []


def test_resume_published_after_halt_emits_resume():
    tracker = HaltTracker()
    halt_only = make_event()
    list(tracker.ingest([halt_only]))

    halt_with_resume = make_event(resume_trade_time="07:30:00")
    out = list(tracker.ingest([halt_with_resume]))
    assert len(out) == 1
    assert out[0][0] == "resume"


def test_resume_only_emitted_once():
    tracker = HaltTracker()
    halt_only = make_event()
    list(tracker.ingest([halt_only]))
    halt_with_resume = make_event(resume_trade_time="07:30:00")
    list(tracker.ingest([halt_with_resume]))
    # Same event re-fetched again
    out = list(tracker.ingest([halt_with_resume]))
    assert out == []


def test_first_sighting_already_resumed_emits_both():
    """Edge case: feed roll-on shows a halt that already has resume time."""
    tracker = HaltTracker()
    event = make_event(resume_trade_time="07:30:00")
    out = list(tracker.ingest([event]))
    assert len(out) == 2
    assert out[0][0] == "halt"
    assert out[1][0] == "resume"


def test_cross_feed_dedup_by_halt_id():
    """Same halt event reported by both Nasdaq RSS and NYSE CSV → emit once."""
    tracker = HaltTracker()
    e_nasdaq = make_event(symbol="ARVN")
    e_nyse = HaltEvent(
        symbol="ARVN",
        exchange="NYSE",
        halt_date="2026-05-05",
        halt_time="06:55:32",  # same halt-id as e_nasdaq
        reason_code="T1",
        reason_description="News Pending",
        source="nyse_csv",
    )
    out = list(tracker.ingest([e_nasdaq, e_nyse]))
    assert len(out) == 1
    assert out[0][0] == "halt"


def test_different_halts_same_symbol_different_times():
    """Two halts on same ticker on different dates/times — both emit."""
    tracker = HaltTracker()
    e1 = make_event(date="2026-05-05", time="06:55:32")
    e2 = make_event(date="2026-05-06", time="10:00:00")
    out = list(tracker.ingest([e1, e2]))
    assert len(out) == 2


def _event(symbol="ARVN", date="2026-05-05", time="06:55:32", reason_code="T1",
           source="nasdaq_rss"):
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date=date, halt_time=time,
        reason_code=reason_code, reason_description="", source=source,
    )


# --- Fix #4: halt_id canonicalizes the time string --------------------------
def test_cross_feed_dedup_canonicalizes_unpadded_time():
    """One feed publishes '6:55:32', the other '06:55:32' — same instant, one
    alert. Before the fix these produced different halt_ids and double-alerted."""
    tracker = HaltTracker()
    e_nasdaq = _event(time="6:55:32", source="nasdaq_rss")   # unpadded hour
    e_nyse = _event(time="06:55:32", source="nyse_csv")      # zero-padded
    out = list(tracker.ingest([e_nasdaq, e_nyse]))
    assert len(out) == 1
    assert out[0][0] == "halt"


# --- Fix #3: a bad first source must not shadow a good second source --------
def test_non_emit_first_source_does_not_shadow_emittable_second():
    """Source-1 reports the halt with a non-emit reason (O1) that _emit filters
    and never delivers; source-2 reports the SAME halt_id with an emittable code
    (T1). The good record must still be re-yielded so it can be delivered.
    Before the fix the second source was silently shadowed."""
    tracker = HaltTracker()
    bad = _event(reason_code="O1", source="nasdaq_rss")   # non-emit → filtered
    good = _event(reason_code="T1", source="nyse_csv")    # emittable, same id

    out1 = list(tracker.ingest([bad]))
    assert out1 == [("halt", bad)]        # yielded (production _emit filters O1)
    # production _emit does NOT add a filtered halt to emitted_halts:
    assert good.halt_id not in tracker.emitted_halts

    out2 = list(tracker.ingest([good]))
    assert out2 == [("halt", good)]       # re-yielded so the emittable record delivers


def test_upgrade_suppressed_once_halt_delivered():
    """The upgrade re-yield is gated on emitted_halts: once a halt was actually
    delivered we never re-yield it, even if a later source carries a code — no
    double-posting."""
    tracker = HaltTracker()
    bad = _event(reason_code="O1")
    list(tracker.ingest([bad]))
    tracker.emitted_halts.add(bad.halt_id)     # simulate delivery
    good = _event(reason_code="T1", source="nyse_csv")
    assert list(tracker.ingest([good])) == []  # delivered → no re-emit


def test_non_emit_both_sources_no_reyield():
    """If both sources are non-emit there is nothing to upgrade to — no re-yield."""
    tracker = HaltTracker()
    a = _event(reason_code="O1", source="nasdaq_rss")
    b = _event(reason_code="M2", source="nyse_csv")   # also non-emit
    list(tracker.ingest([a]))
    assert list(tracker.ingest([b])) == []
