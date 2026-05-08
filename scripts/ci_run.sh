#!/usr/bin/env bash
# CI wrapper for sa-monitor halt-monitor.
#
# Used by .github/workflows/halt-monitor-{am,pm}.yml. Loads any prior
# state/dedup_state_YYYY-MM-DD.json from the repo, runs the monitor for the
# requested duration, then commits the updated state file + log back to the
# repo so the next workflow run (or a restart) picks up where this one left
# off.
#
# Usage: scripts/ci_run.sh <session_label> <duration_seconds>
#   <session_label>     "am" | "pm"  — used in log filenames + commit messages
#   <duration_seconds>  e.g. 20100 (5h35m for AM), 8700 (2h25m for PM)
#
# Required env:
#   SLACK_WEBHOOK_STREET_ACCOUNT  — webhook URL for #street-account
#   GITHUB_TOKEN                  — auto-provided by Actions, used for git push

set -euo pipefail

SESSION="${1:-unknown}"
DURATION="${2:-3600}"
TODAY=$(date -u +%Y-%m-%d)
LOG_FILE="logs/halt_monitor_${TODAY}_${SESSION}.jsonl"

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

  # Pull/rebase before push in case watchdog or other workflow committed.
  git fetch origin "${GITHUB_REF_NAME:-master}" || true
  git rebase "origin/${GITHUB_REF_NAME:-master}" || git rebase --abort || true

  # Stage state + log; ignore if no changes
  git add -A state/ logs/ || true
  if git diff --cached --quiet; then
    echo "no state/log changes to commit"
  else
    git commit -m "ci: halt-monitor ${SESSION} run for ${TODAY} (exit ${exit_code})"
    git push "https://${GITHUB_ACTOR}:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" \
      "HEAD:${GITHUB_REF_NAME:-master}" || echo "push failed (continuing)"
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

python -m src.halt_monitor \
  --slack live \
  --duration "${DURATION}" \
  --interval 5 \
  --log "${LOG_FILE}" \
  "${EXTRA_ARGS[@]}"
