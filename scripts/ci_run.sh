#!/usr/bin/env bash
# CI wrapper for sa-monitor halt-monitor.
#
# Used by .github/workflows/halt-monitor-{am,pm}.yml. Loads any prior
# state/dedup_state_YYYY-MM-DD.json from the repo, runs the monitor for the
# requested duration, then commits the updated state file + log back to the
# repo so the next workflow run (or a restart) picks up where this one left
# off.
#
# Usage: scripts/ci_run.sh <session_label> <max_duration_seconds> [session_end_utc]
#   <session_label>        "am" | "pm"  — used in log filenames + commit messages
#   <max_duration_seconds> upper bound, e.g. 20100 (5h35m AM), 19500 (5h25m PM)
#   [session_end_utc]      'HH:MM' UTC wall-clock end of the session. When set,
#                          the run is clamped to `end - now` (see below).
#
# Wall-clock session windows (2026-07-28). GitHub delays free-tier crons by
# ~2h, and a session that ran "<duration> from launch" dragged its watched
# window along with the delay — the PM session routinely started after the
# 16:00 ET close it exists to watch. Sessions are now pinned to a wall-clock
# END: a late start shortens the run instead of sliding it. The AM session
# therefore always releases the `halt-monitor-session` concurrency group at
# 19:00 UTC, so a late AM can no longer starve PM through the close, and a
# duplicate/very-late PM run exits as a no-op instead of watching a shut
# market. Math + tests: scripts/session_window.py, tests/test_session_window.py.
# Override for an out-of-hours smoke test with IGNORE_SESSION_WINDOW=1.
#
# Required env:
#   SLACK_WEBHOOK_STREET_ACCOUNT  — webhook URL for #street-account
#   GITHUB_TOKEN                  — auto-provided by Actions, used for git push

set -euo pipefail

SESSION="${1:-unknown}"
DURATION="${2:-3600}"
SESSION_END_UTC="${3:-${SESSION_END_UTC:-}}"
TODAY=$(date -u +%Y-%m-%d)
LOG_FILE="logs/halt_monitor_${TODAY}_${SESSION}.jsonl"

# Clamp to the wall-clock window BEFORE anything else (before the calendar
# fetch and before the commit-state trap is armed) so a run outside its window
# costs nothing and leaves no half-state behind.
if [ -n "$SESSION_END_UTC" ] && [ "${IGNORE_SESSION_WINDOW:-0}" != "1" ]; then
  REQUESTED="$DURATION"
  DURATION=$(python scripts/session_window.py \
    --end-utc "$SESSION_END_UTC" --max-duration "$REQUESTED")
  echo "[window] session=${SESSION} end=${SESSION_END_UTC} UTC now=$(date -u +%H:%M) UTC requested=${REQUESTED}s effective=${DURATION}s"
  if [ "$DURATION" -le 0 ]; then
    # Not a failure: the window this session watches has already closed (a
    # cron delivered hours late, or a redundant watchdog recovery). Exit clean
    # and LOUD rather than burning a full session on a shut market.
    echo "::notice title=halt-monitor ${SESSION} skipped::window ending ${SESSION_END_UTC} UTC has already closed on ${TODAY} - nothing to watch, exiting without running the monitor"
    exit 0
  fi
  if [ "$DURATION" -lt "$REQUESTED" ]; then
    echo "::warning title=halt-monitor ${SESSION} started late::run shortened from ${REQUESTED}s to ${DURATION}s to hold the ${SESSION_END_UTC} UTC session end (delayed cron delivery)"
  fi
fi

# Phase 2 enrichment calendars — fetched fresh each session from sibling
# public repos. Best-effort: missing/stale calendars only mean the "Note:"
# context line won't appear on alerts; the halt monitor still runs.
EARNINGS_CALENDAR_URL="${EARNINGS_CALENDAR_URL:-https://raw.githubusercontent.com/jroypeterson/earnings-agent/main/exports/upcoming_events.json}"
ANALYST_DAYS_CALENDAR_URL="${ANALYST_DAYS_CALENDAR_URL:-https://raw.githubusercontent.com/jroypeterson/analyst-days/master/exports/upcoming_events.json}"
EARNINGS_CALENDAR_PATH="data/calendars/earnings_upcoming.json"
ANALYST_DAYS_CALENDAR_PATH="data/calendars/analyst_days_upcoming.json"

mkdir -p logs state data/calendars

echo "::group::fetch enrichment calendars"
for pair in "earnings|$EARNINGS_CALENDAR_URL|$EARNINGS_CALENDAR_PATH" \
            "analyst-days|$ANALYST_DAYS_CALENDAR_URL|$ANALYST_DAYS_CALENDAR_PATH"; do
  IFS='|' read -r label url out <<< "$pair"
  if curl -sS -fL --max-time 30 "$url" -o "$out.tmp"; then
    mv "$out.tmp" "$out"
    bytes=$(wc -c < "$out")
    echo "[$label] fetched ${bytes}b -> $out"
  else
    rm -f "$out.tmp"
    echo "[$label] fetch failed; enrichment will no-op for this calendar"
  fi
done
echo "::endgroup::"

echo "::group::ci_run config"
echo "session=${SESSION}"
echo "duration=${DURATION}s ($((DURATION / 60))m)"
echo "today_utc=${TODAY}"
echo "log=${LOG_FILE}"
echo "state_dir contents:"
ls -la state/ || true
echo "::endgroup::"

# Trap to commit-state-on-exit even if the runner panics.
commit_state() {
  local exit_code=$?
  echo "::group::commit state + log (exit_code=${exit_code})"
  git config user.name "sa-monitor-ci"
  git config user.email "sa-monitor-ci@users.noreply.github.com"

  local branch="${GITHUB_REF_NAME:-main}"

  # Stage + commit FIRST, then rebase/push. The previous ordering rebased before
  # staging, so the run's freshly-written (tracked) log file was an unstaged
  # change and `git rebase` aborted with "cannot rebase: You have unstaged
  # changes" — the branch never incorporated concurrent commits, the push was
  # rejected non-fast-forward, and the failure was swallowed. PM runs collide
  # daily (delayed cron + watchdog dispatch both commit), so PM state/logs were
  # silently lost since 2026-06-02. Committing first gives rebase a clean tree.
  git add -A state/ logs/ || true
  if git diff --cached --quiet; then
    echo "no state/log changes to commit"
    echo "::endgroup::"
    return $exit_code
  fi

  git commit -m "ci: halt-monitor ${SESSION} run for ${TODAY} (exit ${exit_code})"

  # Push with rebase-retry: another session (or the watchdog) may have advanced
  # the branch while this 2h25m–5h35m run was active. The working tree is clean
  # now (commit made), so the rebase won't choke; --autostash guards any stray
  # unstaged change defensively.
  local pushed=0 attempt
  for attempt in 1 2 3 4 5; do
    if git push "https://${GITHUB_ACTOR}:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" \
        "HEAD:${branch}"; then
      pushed=1
      break
    fi
    echo "push attempt ${attempt} rejected — fetch + rebase onto origin/${branch} + retry"
    git fetch origin "${branch}" || true
    git rebase --autostash "origin/${branch}" || { git rebase --abort || true; }
  done

  if [ "$pushed" -ne 1 ]; then
    # Visible alarm rather than a silent skip (feedback_no_silent_failures).
    echo "::warning::sa-monitor ${SESSION} ${TODAY}: state/log push FAILED after 5 attempts — this session's state was NOT persisted"
  fi
  echo "::endgroup::"
  return $exit_code
}
trap commit_state EXIT

EXTRA_ARGS=()
if [ -f "$EARNINGS_CALENDAR_PATH" ]; then
  EXTRA_ARGS+=(--earnings-calendar "$EARNINGS_CALENDAR_PATH")
fi
if [ -f "$ANALYST_DAYS_CALENDAR_PATH" ]; then
  EXTRA_ARGS+=(--analyst-days-calendar "$ANALYST_DAYS_CALENDAR_PATH")
fi

# Phase 2 slice 2B: enable news cross-ref (PRN/BW/GNW polled every 30s).
# Opt-out via DISABLE_NEWS_CROSS_REF=1 if rate-limits become an issue.
if [ "${DISABLE_NEWS_CROSS_REF:-0}" != "1" ]; then
  EXTRA_ARGS+=(--news-cross-ref)
fi

# HC event-wire: classify the already-fetched PR wire for FDA actions +
# clinical readouts on covered names. Consumes the same news poll (no new
# HTTP). Opt-out via DISABLE_HC_EVENTS=1.
if [ "${DISABLE_HC_EVENTS:-0}" != "1" ]; then
  EXTRA_ARGS+=(--hc-events)
fi

python -m src.halt_monitor \
  --slack live \
  --duration "${DURATION}" \
  --interval 5 \
  --log "${LOG_FILE}" \
  "${EXTRA_ARGS[@]}"
