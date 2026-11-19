"""Tests for state persistence."""
from pathlib import Path

import pytest

from src import state
from src.dedup import HaltTracker
from src.feeds.types import HaltEvent


def make_event(symbol="VRDN", date="2026-05-05", time_="06:55:32"):
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date=date, halt_time=time_,
        reason_code="T1", reason_description="News Pending", source="nasdaq_rss",
    )


def test_save_writes_file(tmp_path):
    tracker = HaltTracker()
    list(tracker.ingest([make_event("VRDN")]))
    path = state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")
    assert path.exists()
    assert path.read_text().strip().startswith("{")


def test_load_rehydrates_halt_ids(tmp_path):
    tracker = HaltTracker()
    list(tracker.ingest([make_event("VRDN"), make_event("ARVN", time_="11:23:00")]))
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert ("VRDN", "2026-05-05", "06:55:32") in fresh.seen_halts
    assert ("ARVN", "2026-05-05", "11:23:00") in fresh.seen_halts


def test_load_no_file_returns_empty_tracker(tmp_path):
    fresh = state.load(state_dir=tmp_path, day_key="2099-01-01")
    assert len(fresh) == 0


def test_load_corrupt_file_fails_loud(tmp_path):
    """A corrupt state file must NOT silently reset to empty (that would re-spam
    every prior halt). It fails loud so the runner crashes with a signal."""
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text("not valid json")
    with pytest.raises(state.StateError):
        state.load(state_dir=tmp_path, day_key="2026-05-05")


def test_load_wrong_schema_fails_loud(tmp_path):
    """An unexpected schema_version means producer/consumer disagree on shape —
    fail loud rather than misread it into a silent fresh start."""
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text('{"schema_version": 99, "halts": []}')
    with pytest.raises(state.StateError):
        state.load(state_dir=tmp_path, day_key="2026-05-05")


def test_load_missing_file_still_starts_fresh(tmp_path):
    """A genuinely absent file (normal first poll of the day) is NOT an error —
    only an EXISTING-but-corrupt file fails loud."""
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert len(fresh) == 0


def test_save_reload_dedup_works(tmp_path):
    """Whole point of persistence: a re-fetched halt after restore doesn't re-fire."""
    tracker = HaltTracker()
    e = make_event("VRDN")
    list(tracker.ingest([e]))
    # Production shape of a DELIVERED halt: _emit records it in emitted_halts.
    # (An id that is only seen, never delivered, may still be delivered after a
    # restart — see test_restored_undelivered_halt_can_still_deliver.)
    tracker.emitted_halts.add(e.halt_id)
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-05-05")
    out = list(rehydrated.ingest([e]))  # same event, second sighting
    assert out == []  # already delivered, no emit


def test_resumes_round_trip(tmp_path):
    tracker = HaltTracker()
    e_with_resume = HaltEvent(
        symbol="INSM", exchange="Nasdaq", halt_date="2026-04-07",
        halt_time="16:01:15", reason_code="T1", reason_description="News Pending",
        resume_trade_time="16:30:00", source="nasdaq_rss",
    )
    list(tracker.ingest([e_with_resume]))  # emits halt + resume
    tracker.emitted_halts.add(e_with_resume.halt_id)  # delivered (production shape)
    tracker.resumes_delivered.add(e_with_resume.halt_id)  # resume delivered too
    state.save(tracker, state_dir=tmp_path, day_key="2026-04-07")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-04-07")
    out = list(rehydrated.ingest([e_with_resume]))
    assert out == []  # halt seen + resume already emitted


def test_followed_up_round_trip(tmp_path):
    """§7 follow-up markers persist so a restart never re-emits a follow-up."""
    tracker = HaltTracker()
    e = make_event("INSM", date="2026-04-07", time_="16:01:15")
    list(tracker.ingest([e]))
    tracker.followed_up.add(e.halt_id)
    state.save(tracker, state_dir=tmp_path, day_key="2026-04-07")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-04-07")
    assert ("INSM", "2026-04-07", "16:01:15") in rehydrated.followed_up


def test_emitted_halts_round_trip(tmp_path):
    """Delivered-halt markers persist so the follow-up delivery gate survives
    a restart (a follow-up only fires for a halt we actually delivered)."""
    tracker = HaltTracker()
    e = make_event("VRDN")
    list(tracker.ingest([e]))
    tracker.emitted_halts.add(e.halt_id)
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert ("VRDN", "2026-05-05", "06:55:32") in rehydrated.emitted_halts


def test_load_old_file_without_new_fields(tmp_path):
    """A pre-§7 state file (no emitted_halts / followed_up keys) rehydrates to
    empty sets and still loads its halts."""
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text(
        '{"schema_version": 1, "trading_day_et": "2026-05-05", '
        '"halts": [["VRDN","2026-05-05","06:55:32"]], "resumes_emitted": []}'
    )
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert fresh.emitted_halts == set()
    assert fresh.followed_up == set()
    assert ("VRDN", "2026-05-05", "06:55:32") in fresh.seen_halts


def test_cleanup_deletes_old_files(tmp_path):
    (tmp_path / "dedup_state_2020-01-01.json").write_text("{}")
    (tmp_path / "dedup_state_2099-12-31.json").write_text("{}")
    deleted = state.cleanup_old(state_dir=tmp_path, keep_days=7)
    assert deleted == 1
    assert (tmp_path / "dedup_state_2099-12-31.json").exists()
    assert not (tmp_path / "dedup_state_2020-01-01.json").exists()


# --- Finding 2 (2026-11-18): the delivery ledger, not observation, gates a
# restored halt -------------------------------------------------------------

def _o1(symbol="VRDN", date="2026-05-05", time_="06:55:32"):
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date=date, halt_time=time_,
        reason_code="O1", reason_description="Operations Halt", source="nasdaq_rss",
    )


def test_restored_undelivered_halt_can_still_deliver(tmp_path):
    """Session 1 saw only a non-emit (O1) copy, so nothing was delivered. After
    a restart the emittable T1 copy arrives: it must still deliver."""
    tracker = HaltTracker()
    list(tracker.ingest([_o1()]))
    assert not tracker.emitted_halts
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-05-05")
    out = list(rehydrated.ingest([make_event("VRDN")]))
    assert [k for k, _ in out] == ["halt"]
    assert out[0][1].reason_code == "T1"


def test_restored_delivered_halt_does_not_redeliver(tmp_path):
    tracker = HaltTracker()
    list(tracker.ingest([_o1()]))
    tracker.emitted_halts.add(_o1().halt_id)
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert list(rehydrated.ingest([make_event("VRDN")])) == []


# --- Finding 5 (2026-11-18): the delivery ledger outlives its day file ------

def _resumed(symbol="CRIS", date="2026-07-02", time_="19:50:00", resume="09:30:00"):
    return HaltEvent(
        symbol=symbol, exchange="Nasdaq", halt_date=date, halt_time=time_,
        reason_code="T1", reason_description="News Pending",
        resume_trade_time=resume, source="nasdaq_rss",
    )


def _deliver_on(tmp_path, day_key, event, *, hc_key=None):
    tracker = HaltTracker()
    list(tracker.ingest([event]))
    tracker.emitted_halts.add(event.halt_id)
    if event.is_resumed:
        tracker.resumes_delivered.add(event.halt_id)  # _emit's delivery mark
    if hc_key:
        tracker.hc_events_emitted.add(hc_key)
    state.save(tracker, state_dir=tmp_path, day_key=day_key)
    return tracker


def test_multi_day_halt_does_not_realert_next_day(tmp_path):
    """CRIS halted 2026-07-02 alerted on 07-03 AND 07-06: the new day's empty
    file forgot the delivery. A prior-day delivery must suppress it."""
    e = make_event("CRIS", date="2026-07-02", time_="19:50:00")
    _deliver_on(tmp_path, "2026-07-03", e)

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")
    assert list(day2.ingest([e])) == []


def test_multi_day_halt_resume_on_later_day_still_delivers(tmp_path):
    e = make_event("CRIS", date="2026-07-02", time_="19:50:00")
    _deliver_on(tmp_path, "2026-07-03", e)

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")
    out = list(day2.ingest([_resumed()]))
    assert [k for k, _ in out] == ["resume"]


def test_prior_day_resume_is_not_redelivered(tmp_path):
    _deliver_on(tmp_path, "2026-07-03", _resumed())  # halt + resume both delivered

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")
    assert list(day2.ingest([_resumed()])) == []


def test_prior_day_hc_key_is_carried_but_not_resaved(tmp_path):
    key = "prn-123|VRDN|fda_approval"
    _deliver_on(tmp_path, "2026-07-03", make_event("VRDN", date="2026-07-03"),
                hc_key=key)

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")
    assert key in day2.hc_events_prior
    assert key not in day2.hc_events_emitted  # day files hold only their own
    path = state.save(day2, state_dir=tmp_path, day_key="2026-07-06")
    import json
    assert key not in json.loads(path.read_text())["hc_events_emitted"]


def test_corrupt_prior_day_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "dedup_state_2026-07-03.json").write_text("not valid json")
    e = make_event("CRIS", date="2026-07-02", time_="19:50:00")
    _deliver_on(tmp_path, "2026-07-02", e)

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")  # must not raise
    assert e.halt_id in day2.emitted_halts  # the good prior file still carried


def test_halt_older_than_keep_days_is_not_carried(tmp_path):
    old = make_event("CRIS", date="2026-06-20", time_="19:50:00")
    _deliver_on(tmp_path, "2026-07-03", old)  # file in window, halt_date is not

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06", keep_days=7)
    assert old.halt_id not in day2.emitted_halts
    assert old.halt_id not in day2.seen_halts


def test_prior_file_outside_window_is_ignored(tmp_path):
    e = make_event("CRIS", date="2026-06-20", time_="19:50:00")
    _deliver_on(tmp_path, "2026-06-20", e)

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06", keep_days=7)
    assert e.halt_id not in day2.emitted_halts


def test_filtered_resume_mark_is_not_carried(tmp_path):
    """resumes_emitted is marked BEFORE _emit filters, so a prior-day file can
    hold a resume that was never posted (a pre-fix T3). Only resumes_delivered
    is carried, so the real resume still delivers the next day."""
    e = make_event("CRIS", date="2026-07-02", time_="19:50:00")
    tracker = HaltTracker()
    list(tracker.ingest([e]))
    tracker.emitted_halts.add(e.halt_id)
    tracker.resumes_emitted.add(e.halt_id)  # filtered, never delivered
    state.save(tracker, state_dir=tmp_path, day_key="2026-07-03")

    day2 = state.load(state_dir=tmp_path, day_key="2026-07-06")
    assert [k for k, _ in day2.ingest([_resumed()])] == ["resume"]


def test_resumes_delivered_round_trips(tmp_path):
    tracker = HaltTracker()
    tracker.resumes_delivered.add(("VRDN", "2026-05-05", "06:55:32"))
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert ("VRDN", "2026-05-05", "06:55:32") in fresh.resumes_delivered


def test_same_day_restart_does_not_trust_filtered_resume_mark(tmp_path):
    """Codex R2: a same-day file whose resumes_emitted holds a filtered (never
    posted) resume must not suppress the real resume after a restart."""
    e = make_event("VRDN")
    tracker = HaltTracker()
    list(tracker.ingest([e]))
    tracker.emitted_halts.add(e.halt_id)
    tracker.resumes_emitted.add(e.halt_id)  # filtered attempt, not delivered
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    resumed = HaltEvent(
        symbol="VRDN", exchange="Nasdaq", halt_date="2026-05-05",
        halt_time="06:55:32", reason_code="T1", reason_description="News Pending",
        resume_trade_time="07:30:00", source="nasdaq_rss",
    )
    assert [k for k, _ in fresh.ingest([resumed])] == ["resume"]


def test_legacy_same_day_file_keeps_resume_marks(tmp_path):
    """Legacy policy: a file with no resumes_delivered key keeps its stored
    resumes_emitted (pre-2026-11-19 behaviour)."""
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text(
        '{"schema_version": 1, "halts": [["VRDN","2026-05-05","06:55:32"]], '
        '"resumes_emitted": [["VRDN","2026-05-05","06:55:32"]], '
        '"emitted_halts": [["VRDN","2026-05-05","06:55:32"]]}'
    )
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert ("VRDN", "2026-05-05", "06:55:32") in fresh.resumes_emitted
