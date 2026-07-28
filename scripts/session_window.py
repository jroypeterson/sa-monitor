#!/usr/bin/env python3
"""Wall-clock session window math for the halt-monitor CI sessions.

Why this exists
---------------
GitHub Actions delivers free-tier scheduled crons late — routinely by ~2 hours
under load. The AM/PM sessions used to run "N seconds from whenever the job
happened to start", so a delayed launch dragged the whole watched window
forward with it. The PM session (cron 19:05 UTC, 2h25m) frequently started
AFTER the 16:00 ET close it exists to watch — the single highest-halt-density
window of the day was missed on a feed whose entire value is timeliness.

The fix is to define a session by the wall-clock time it must END, not by how
long it runs:

    duration = min(max_duration, session_end_utc - now)

A late start therefore SHORTENS the run instead of sliding it past the close,
which has two useful consequences:

1. The AM session always releases the `halt-monitor-session` concurrency group
   at a fixed wall-clock instant (19:00 UTC), so the PM session cannot be
   starved by a late AM run.
2. A duplicate/very-late PM run (e.g. a watchdog recovery colliding with a
   cron that finally landed) computes a non-positive window and exits as a
   no-op instead of burning 2h25m watching a closed market.

`--min-duration` guards the sliver case: a window with under N seconds left is
not worth the runner setup plus the state commit-back, so it reports 0 too.

Usage
-----
    python scripts/session_window.py --end-utc 21:30 --max-duration 19500
        -> effective duration in whole seconds on stdout ("0" = window closed)

    Optional --now (ISO 8601, UTC assumed when naive) for tests / dry runs.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timezone


def parse_hhmm(value: str) -> time:
    """Parse an 'HH:MM' UTC wall-clock time. Raises ValueError when malformed."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"out-of-range HH:MM: {value!r}")
    return time(hour=hour, minute=minute)


def effective_duration(
    now: datetime,
    end_utc: str,
    max_duration: int,
    min_duration: int = 300,
) -> int:
    """Seconds this session should run for, given the wall clock.

    `end_utc` is an 'HH:MM' UTC time on `now`'s UTC date. Returns 0 when the
    window has already closed (or has less than `min_duration` left), which the
    caller must treat as "skip this run", not as a failure.
    """
    if max_duration <= 0:
        raise ValueError(f"max_duration must be positive, got {max_duration}")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    end = datetime.combine(now.date(), parse_hhmm(end_utc), tzinfo=timezone.utc)
    remaining = int((end - now).total_seconds())
    if remaining < min_duration:
        return 0
    return min(max_duration, remaining)


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Effective halt-monitor session duration from a wall-clock end time"
    )
    parser.add_argument("--end-utc", required=True,
                        help="wall-clock end of the session, 'HH:MM' UTC")
    parser.add_argument("--max-duration", type=int, required=True,
                        help="upper bound in seconds (the on-time session length)")
    parser.add_argument("--min-duration", type=int, default=300,
                        help="report 0 when fewer than this many seconds remain "
                             "(default 300 — a shorter sliver isn't worth the setup)")
    parser.add_argument("--now", default=None,
                        help="ISO 8601 override for the current time (tests/dry runs)")
    args = parser.parse_args(argv)

    seconds = effective_duration(
        _parse_now(args.now), args.end_utc, args.max_duration, args.min_duration
    )
    print(seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
