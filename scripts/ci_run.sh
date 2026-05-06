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

mkdir -p logs state

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

python -m src.halt_monitor \
  --slack live \
  --duration "${DURATION}" \
  --interval 5 \
  --log "${LOG_FILE}"
