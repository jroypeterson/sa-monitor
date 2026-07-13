"""Persistent dedup state for sa-monitor halt-monitor.

The halt-id dedup tracker (HaltTracker in src/dedup.py) is in-memory only.
That works fine for one continuous run, but if the runner restarts mid-session
(GH Actions job timeout, manual rerun, exception), every previously-seen halt
re-emits as new on the next poll — which means re-posting them all to Slack.

This module persists the halt-id set (and the resumes-emitted set) to disk
between polls so a fresh start can rehydrate without spamming.

State lives under `state/` keyed by trading day (ET). On boot, the runner
reads today's file; on each poll, it writes the full set atomically. Stale
files older than 7 days get cleaned up on boot to keep the dir tidy.

File format: JSON
  {
    "trading_day_et": "2026-05-05",
    "saved_at_utc": "2026-05-05T20:30:00+00:00",
    "halts": [["VRDN","2026-05-05","06:55:32"], …],
    "resumes_emitted": [["INSM","2026-04-07","16:01:15"], …],
    "emitted_halts": [["VRDN","2026-05-05","06:55:32"], …],
    "followed_up": [["INSM","2026-04-07","16:01:15"], …]
  }
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
from pathlib import Path

from .dedup import HaltTracker
from .feeds.types import HaltEvent

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = REPO_ROOT / "state"
ET = dt.timezone(dt.timedelta(hours=-4))  # EDT during DST; close enough for daily-rotation key


def _today_et_key() -> str:
    return dt.datetime.now(ET).strftime("%Y-%m-%d")


def _state_file_for(day_key: str, state_dir: Path) -> Path:
    return state_dir / f"dedup_state_{day_key}.json"


def save(tracker: HaltTracker, *, state_dir: Path = DEFAULT_STATE_DIR,
         day_key: str = "") -> Path:
    """Persist the tracker's halt-id sets to disk atomically."""
    state_dir.mkdir(parents=True, exist_ok=True)
    day_key = day_key or _today_et_key()
    path = _state_file_for(day_key, state_dir)

    payload = {
        "schema_version": 1,
        "trading_day_et": day_key,
        "saved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "halts": [list(hid) for hid in tracker.seen_halts.keys()],
        "resumes_emitted": [list(hid) for hid in tracker.resumes_emitted],
        "emitted_halts": [list(hid) for hid in tracker.emitted_halts],
        "followed_up": [list(hid) for hid in tracker.followed_up],
        "hc_events_emitted": sorted(tracker.hc_events_emitted),
    }

    # Atomic write: tmp file → rename
    fd, tmp_path = tempfile.mkstemp(dir=str(state_dir), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return path


def load(*, state_dir: Path = DEFAULT_STATE_DIR, day_key: str = "") -> HaltTracker:
    """Rehydrate a tracker from today's state file (if any)."""
    day_key = day_key or _today_et_key()
    path = _state_file_for(day_key, state_dir)
    tracker = HaltTracker()
    if not path.exists():
        log.info("state: no prior file at %s; starting fresh", path)
        return tracker
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("state: failed to read %s (%s); starting fresh", path, exc)
        return tracker

    if payload.get("schema_version") != 1:
        log.warning(
            "state: unexpected schema_version %r in %s; starting fresh",
            payload.get("schema_version"), path,
        )
        return tracker

    halts = [tuple(h) for h in payload.get("halts", [])]
    resumes = {tuple(r) for r in payload.get("resumes_emitted", [])}
    # Additive fields (introduced after schema v1 shipped); older state files
    # simply lack them and rehydrate to empty sets.
    emitted_halts = {tuple(e) for e in payload.get("emitted_halts", [])}
    followed_up = {tuple(f) for f in payload.get("followed_up", [])}
    # HC event-wire delivery-dedup — string keys, not HaltId tuples.
    hc_events_emitted = set(payload.get("hc_events_emitted", []))

    # Pre-fill seen_halts with placeholder HaltEvents — we only need the
    # halt_ids to be populated so dedup works; the full event history isn't
    # required for the runner's correctness.
    for hid in halts:
        symbol, halt_date, halt_time = hid
        tracker.seen_halts[(symbol, halt_date, halt_time)] = HaltEvent(
            symbol=symbol,
            exchange="",
            halt_date=halt_date,
            halt_time=halt_time,
            reason_code="",
            reason_description="",
            source="restored_from_state",
        )
    tracker.resumes_emitted = resumes
    tracker.emitted_halts = emitted_halts
    tracker.followed_up = followed_up
    tracker.hc_events_emitted = hc_events_emitted
    log.info(
        "state: rehydrated from %s (%d halts, %d resumes, %d emitted, "
        "%d followed_up, %d hc_events)",
        path, len(halts), len(resumes), len(emitted_halts), len(followed_up),
        len(hc_events_emitted),
    )
    return tracker


def cleanup_old(*, state_dir: Path = DEFAULT_STATE_DIR, keep_days: int = 7) -> int:
    """Delete state files older than keep_days. Returns count deleted."""
    if not state_dir.exists():
        return 0
    cutoff = dt.datetime.now(ET) - dt.timedelta(days=keep_days)
    cutoff_key = cutoff.strftime("%Y-%m-%d")
    deleted = 0
    for f in state_dir.glob("dedup_state_*.json"):
        try:
            day = f.stem.replace("dedup_state_", "")
            if day < cutoff_key:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted
