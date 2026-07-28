"""Wall-clock session-window math (scripts/session_window.py).

The regression these guard: GitHub delays free-tier crons by ~2h, and the old
"run N seconds from launch" model slid the PM session past the 16:00 ET close.
Sessions are now pinned to a wall-clock END, so a late start shortens the run
rather than moving the watched window.

`scripts/` is not a package, so load the module by path (same idiom as
tests/test_build_universe.py).
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "session_window.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("session_window", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load_module()


def _utc(hh, mm):
    return datetime(2026, 7, 28, hh, mm, tzinfo=timezone.utc)


# --- the on-time case is unchanged behaviour --------------------------------

def test_on_time_pm_start_gets_the_full_capped_session():
    """PM cron 16:05 UTC, end 21:30 UTC, cap 19500s (5h25m) -> the full cap."""
    assert sw.effective_duration(_utc(16, 5), "21:30", 19500) == 19500


def test_on_time_am_start_gets_the_full_capped_session():
    assert sw.effective_duration(_utc(13, 25), "19:00", 20100) == 20100


# --- the bug: a late start must not slide the window ------------------------

def test_two_hour_late_am_still_ends_at_its_wall_clock_time():
    """A 2h-late AM start ends at 19:00 UTC regardless — which is what frees
    the concurrency group in time for the PM session to cover the close."""
    assert sw.effective_duration(_utc(15, 25), "19:00", 20100) == 3 * 3600 + 35 * 60


def test_pm_started_at_am_handoff_still_covers_the_close():
    """PM picking up at 19:00 UTC runs to 21:30 UTC = 17:30 ET (EDT) /
    16:30 ET (EST) — the 15:30-16:15 ET window is inside it either way."""
    assert sw.effective_duration(_utc(19, 0), "21:30", 19500) == 2 * 3600 + 30 * 60


def test_three_hour_late_pm_still_covers_1530_et_edt():
    """Worst tolerated delivery: 16:05 cron landing at 19:25 UTC still starts
    before 19:30 UTC (= 15:30 ET during EDT) and runs past the close."""
    assert sw.effective_duration(_utc(19, 25), "21:30", 19500) == 2 * 3600 + 5 * 60


# --- window already closed -> no-op, never a full redundant run -------------

def test_window_already_closed_reports_zero():
    assert sw.effective_duration(_utc(21, 30), "21:30", 19500) == 0
    assert sw.effective_duration(_utc(22, 45), "21:30", 19500) == 0


def test_sliver_below_min_duration_reports_zero():
    """Under 5 minutes left isn't worth runner setup + the state commit-back."""
    assert sw.effective_duration(_utc(21, 27), "21:30", 19500) == 0
    assert sw.effective_duration(_utc(21, 24), "21:30", 19500) == 360


def test_min_duration_is_configurable():
    assert sw.effective_duration(_utc(21, 27), "21:30", 19500, min_duration=60) == 180


# --- input handling ---------------------------------------------------------

def test_naive_now_is_treated_as_utc():
    naive = datetime(2026, 7, 28, 19, 0)
    assert sw.effective_duration(naive, "21:30", 19500) == 2 * 3600 + 30 * 60


def test_non_utc_now_is_converted_before_comparing():
    from datetime import timedelta, timezone as tz
    aware = datetime(2026, 7, 28, 15, 0, tzinfo=tz(timedelta(hours=-4)))  # 19:00 UTC
    assert sw.effective_duration(aware, "21:30", 19500) == 2 * 3600 + 30 * 60


@pytest.mark.parametrize("bad", ["2130", "21:30:00", "", "25:00", "21:75"])
def test_malformed_end_time_raises(bad):
    with pytest.raises(ValueError):
        sw.effective_duration(_utc(19, 0), bad, 19500)


def test_non_positive_max_duration_raises():
    with pytest.raises(ValueError):
        sw.effective_duration(_utc(19, 0), "21:30", 0)


# --- CLI contract used by scripts/ci_run.sh ---------------------------------

def test_cli_prints_bare_integer_seconds(capsys):
    rc = sw.main(["--end-utc", "21:30", "--max-duration", "19500",
                  "--now", "2026-07-28T19:00:00+00:00"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "9000"


def test_cli_prints_zero_when_window_closed(capsys):
    rc = sw.main(["--end-utc", "21:30", "--max-duration", "19500",
                  "--now", "2026-07-28T23:10:00+00:00"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "0"
