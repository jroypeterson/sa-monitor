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


class StateError(RuntimeError):
    """A state file exists but is unusable (corrupt JSON / unexpected schema).

    Raised by `load()` instead of silently returning a fresh tracker: an empty
    tracker would re-emit every previously-seen halt/resume/follow-up/HC alert as
    new on the next poll (a re-spam), with only a log line and no failure signal.
    Failing loud turns a corrupt-state restart into a hard, alarmed startup crash
    (non-zero exit → CI/fleet alarm) rather than a silent alert flood.
    """


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
        "resumes_delivered": [list(hid) for hid in tracker.resumes_delivered],
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


def load(*, state_dir: Path = DEFAULT_STATE_DIR, day_key: str = "",
         keep_days: int = 7) -> HaltTracker:
    """Rehydrate a tracker from today's state file (if any), then carry the
    delivery ledger forward from the other retained day files.

    State files are keyed by day, so reading only today's file made "one alert
    per halt" mean "one per halt per DAY": a multi-day halt still listed in the
    exchange feed re-alerted on every new day (CRIS, halted 2026-07-02, alerted
    on 07-03 and again on 07-06). The carry makes a delivery record outlive the
    file it was written in, for the `keep_days` retention window.
    """
    day_key = day_key or _today_et_key()
    tracker = _load_day_file(_state_file_for(day_key, state_dir))
    _carry_prior_ledgers(tracker, state_dir=state_dir, day_key=day_key,
                         keep_days=keep_days)
    return tracker


def _placeholder(hid: tuple) -> HaltEvent:
    symbol, halt_date, halt_time = hid
    return HaltEvent(
        symbol=symbol,
        exchange="",
        halt_date=halt_date,
        halt_time=halt_time,
        reason_code="",
        reason_description="",
        source="restored_from_state",
    )


def _carry_prior_ledgers(tracker: HaltTracker, *, state_dir: Path,
                         day_key: str, keep_days: int) -> None:
    """Merge delivery records from retained PRIOR-day files into `tracker`.

    - Halts: every prior `emitted_halts` id whose halt_date is within
      `keep_days` of `day_key` is seeded as a seen placeholder and marked
      delivered, with its followed_up membership. A resume first published on
      a later day still delivers, because its id is not in resumes_emitted.
    - Resumes: carried only from the prior file's `resumes_delivered`, never
      from its `resumes_emitted`. ingest() marks resumes_emitted BEFORE _emit
      filters, so that set also holds resumes that were filtered and never
      posted (every pre-2026-11-19 Nasdaq T3 resume); carrying it would
      suppress the real resume on the next day. A file written before
      resumes_delivered existed carries no resumes: at worst a resume that
      was delivered then is re-sent once, which beats losing one.
    - HC events: prior keys go to `tracker.hc_events_prior`, which is NOT saved,
      so day files do not grow without bound.

    Best-effort by design: a corrupt or wrong-schema PRIOR file is logged and
    skipped. Today's file keeps its fail-loud rule (`_load_day_file`), because
    a lost today-file re-spams the whole session; a lost prior file only
    re-opens the narrower cross-day window this carry exists to close.
    """
    if not state_dir.exists():
        return
    try:
        today = dt.date.fromisoformat(day_key)
    except ValueError:
        log.warning("state: day_key %r is not an ISO date; skipping prior-day carry",
                    day_key)
        return
    oldest_key = (today - dt.timedelta(days=keep_days)).isoformat()
    carried_halts = 0
    carried_hc = 0
    for f in sorted(state_dir.glob("dedup_state_*.json")):
        file_day = f.stem.replace("dedup_state_", "")
        if not (oldest_key <= file_day < day_key):
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError(
                    f"unexpected schema_version "
                    f"{payload.get('schema_version') if isinstance(payload, dict) else None!r}"
                )
            emitted = {tuple(e) for e in payload.get("emitted_halts", [])}
            resumes = {tuple(r) for r in payload.get("resumes_delivered", [])}
            followed = {tuple(x) for x in payload.get("followed_up", [])}
            hc_keys = set(payload.get("hc_events_emitted", []))
        except (OSError, ValueError, TypeError) as exc:
            # json.JSONDecodeError is a ValueError subclass.
            log.warning("state: prior-day file %s is unusable (%s); skipping it "
                        "for the delivery-ledger carry", f, exc)
            continue
        for hid in emitted:
            if len(hid) != 3 or not (oldest_key <= str(hid[1]) <= day_key):
                continue
            if hid not in tracker.seen_halts:
                tracker.seen_halts[hid] = _placeholder(hid)
            if hid not in tracker.emitted_halts:
                tracker.emitted_halts.add(hid)
                carried_halts += 1
            if hid in resumes:
                tracker.resumes_emitted.add(hid)
                tracker.resumes_delivered.add(hid)
            if hid in followed:
                tracker.followed_up.add(hid)
        new_hc = hc_keys - tracker.hc_events_emitted - tracker.hc_events_prior
        tracker.hc_events_prior |= new_hc
        carried_hc += len(new_hc)
    if carried_halts or carried_hc:
        log.info("state: carried %d delivered halts and %d HC events from prior "
                 "day files (window %s..%s)", carried_halts, carried_hc,
                 oldest_key, day_key)


def _load_day_file(path: Path) -> HaltTracker:
    """Rehydrate a tracker from one day's state file (if any). Fails loud on a
    file that exists but is unusable."""
    tracker = HaltTracker()
    if not path.exists():
        # A genuinely absent file is the normal first-poll-of-the-day case:
        # start fresh, no alarm.
        log.info("state: no prior file at %s; starting fresh", path)
        return tracker
    # From here the file EXISTS. If it is unreadable/corrupt/wrong-schema we must
    # NOT silently reset to empty — that would re-spam every prior halt on the
    # next poll. Fail loud (StateError) so the runner crashes with a signal.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("state: %s exists but is unreadable/corrupt (%s); refusing to "
                  "start fresh (would re-spam prior halts)", path, exc)
        raise StateError(
            f"state file {path} exists but could not be parsed ({exc}). "
            f"Refusing to silently start fresh (would re-emit every prior "
            f"halt/resume/follow-up/HC alert). Inspect or remove the file."
        ) from exc

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        log.error("state: %s has unexpected schema_version %r; refusing to start "
                  "fresh (would re-spam prior halts)", path, schema_version)
        raise StateError(
            f"state file {path} has schema_version {schema_version!r}, expected 1. "
            f"Refusing to silently start fresh (would re-emit every prior "
            f"halt/resume/follow-up/HC alert). Inspect or remove the file."
        )

    halts = [tuple(h) for h in payload.get("halts", [])]
    resumes = {tuple(r) for r in payload.get("resumes_emitted", [])}
    # Additive fields (introduced after schema v1 shipped); older state files
    # simply lack them and rehydrate to empty sets.
    emitted_halts = {tuple(e) for e in payload.get("emitted_halts", [])}
    followed_up = {tuple(f) for f in payload.get("followed_up", [])}
    # Same-day resume dedup is seeded from the DELIVERY ledger, not from the
    # attempt set: ingest() marks resumes_emitted before _emit filters, so it
    # also holds resumes that were filtered and never posted, and trusting it
    # after a restart would suppress the real resume when it arrives. A filtered
    # resume therefore re-yields once per restart and is filtered (and logged)
    # again, which is harmless.
    # Legacy policy: a file written before resumes_delivered existed has no way
    # to tell a delivery from a filtered attempt, so it keeps its stored
    # resumes_emitted unchanged (the pre-2026-11-19 behaviour). Such files are
    # day-keyed and age out of the 7-day retention.
    has_delivery_ledger = "resumes_delivered" in payload
    resumes_delivered = {tuple(r) for r in payload.get("resumes_delivered", [])}
    if has_delivery_ledger:
        resumes = set(resumes_delivered)
    # HC event-wire delivery-dedup — string keys, not HaltId tuples.
    hc_events_emitted = set(payload.get("hc_events_emitted", []))

    # Pre-fill seen_halts with placeholder HaltEvents — we only need the
    # halt_ids to be populated so dedup works; the full event history isn't
    # required for the runner's correctness.
    for hid in halts:
        tracker.seen_halts[hid] = _placeholder(hid)
    tracker.resumes_emitted = resumes
    tracker.resumes_delivered = resumes_delivered
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
