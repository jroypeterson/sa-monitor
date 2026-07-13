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


def test_load_corrupt_file_returns_empty_tracker(tmp_path, caplog):
    path = tmp_path / "dedup_state_2026-05-05.json"
    path.write_text("not valid json")
    fresh = state.load(state_dir=tmp_path, day_key="2026-05-05")
    assert len(fresh) == 0


def test_save_reload_dedup_works(tmp_path):
    """Whole point of persistence: a re-fetched halt after restore doesn't re-fire."""
    tracker = HaltTracker()
    e = make_event("VRDN")
    list(tracker.ingest([e]))
    state.save(tracker, state_dir=tmp_path, day_key="2026-05-05")

    rehydrated = state.load(state_dir=tmp_path, day_key="2026-05-05")
    out = list(rehydrated.ingest([e]))  # same event, second sighting
    assert out == []  # already seen, no emit


def test_resumes_round_trip(tmp_path):
    tracker = HaltTracker()
    e_with_resume = HaltEvent(
        symbol="INSM", exchange="Nasdaq", halt_date="2026-04-07",
        halt_time="16:01:15", reason_code="T1", reason_description="News Pending",
        resume_trade_time="16:30:00", source="nasdaq_rss",
    )
    list(tracker.ingest([e_with_resume]))  # emits halt + resume
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
