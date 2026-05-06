#!/usr/bin/env bash
# One-shot sa-monitor deploy.
#
# Run this ONCE from your local machine to do everything Claude couldn't from
# inside Cowork's sandbox:
#   1. Initialize a git repo if not already
#   2. Create jroypeterson/sa-monitor on GitHub (private)
#   3. Add the SLACK_WEBHOOK_STREET_ACCOUNT repo secret from .secrets/
#   4. Push the workflows + code
#   5. Trigger the AM workflow as a smoke test
#
# Prereqs (all should already be true on your machine):
#   - gh CLI installed + authenticated (`gh auth status` shows green)
#   - git installed
#   - Webhook URL written to ../.secrets/slack_webhook_street_account.txt
#
# Run from the sa-monitor folder:
#   cd "C:\Users\jroyp\Dropbox\Claude Folder\sa-monitor"
#   bash scripts/one_shot_deploy.sh
#
# Idempotent — safe to re-run; it skips steps already completed.

set -euo pipefail

REPO="jroypeterson/sa-monitor"
WEBHOOK_FILE="../.secrets/slack_webhook_street_account.txt"
SECRET_NAME="SLACK_WEBHOOK_STREET_ACCOUNT"

# ---- Sanity checks ------------------------------------------------------

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }
info() { printf "  → %s\n" "$*"; }

bold "Checking prerequisites…"
command -v gh  >/dev/null 2>&1 || fail "gh CLI not installed (https://cli.github.com/)"
command -v git >/dev/null 2>&1 || fail "git not installed"
gh auth status >/dev/null 2>&1 || fail "gh not authenticated; run: gh auth login"
[ -f "$WEBHOOK_FILE" ]         || fail "$WEBHOOK_FILE missing — paste webhook URL there first"
[ -d ".github/workflows" ]     || fail "Not in sa-monitor folder (no .github/workflows/)"
ok "tools + auth + secrets in place"

# ---- Step 1: git init ----------------------------------------------------

bold "Step 1: git init + first commit (if needed)…"
if [ ! -d ".git" ]; then
  git init -b master
  ok "initialized git repo"
else
  ok "git repo already initialized"
fi

if [ -z "$(git log --oneline -n 1 2>/dev/null)" ]; then
  git config user.name  "$(git config --global user.name  || echo 'Jason Peterson')"
  git config user.email "$(git config --global user.email || echo '19582261+jroypeterson@users.noreply.github.com')"
  git add -A
  git commit -m "sa-monitor Phase 1 initial commit (D1-D8)"
  ok "first commit created"
else
  info "commits already present; not re-committing"
fi

# ---- Step 2: create GitHub repo ------------------------------------------

bold "Step 2: create GitHub repo $REPO (private)…"
if gh repo view "$REPO" >/dev/null 2>&1; then
  info "repo $REPO already exists; skipping create"
else
  gh repo create "$REPO" --private --source . --remote origin --push
  ok "repo created and pushed"
fi

# Make sure remote is configured even if repo already existed
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo set-default "$REPO"
  git remote add origin "https://github.com/$REPO.git"
  ok "remote 'origin' wired to $REPO"
fi

# ---- Step 3: add Slack webhook secret ------------------------------------

bold "Step 3: add $SECRET_NAME secret to repo…"
if gh secret list --repo "$REPO" | grep -q "^$SECRET_NAME"; then
  info "secret $SECRET_NAME already set; rotating with current value from $WEBHOOK_FILE"
fi
gh secret set "$SECRET_NAME" --repo "$REPO" < "$WEBHOOK_FILE"
ok "secret stored"

# ---- Step 4: push (in case repo already existed but local commits aren't there) ---

bold "Step 4: push latest to origin/master…"
git push -u origin master 2>&1 | grep -v -E '^(remote: |Enumerating|Counting|Compressing|Writing|Total|To )' || true
ok "push complete"

# ---- Step 5: trigger AM workflow as smoke test ---------------------------

bold "Step 5: trigger AM workflow (smoke test)…"
gh workflow run "halt-monitor — AM session" --repo "$REPO"
ok "workflow dispatched"

bold "Done."
echo
info "Watch the run:    gh run watch --repo $REPO"
info "List workflows:   gh workflow list --repo $REPO"
info "Repo on GitHub:   https://github.com/$REPO"
echo
info "Expect: a Slack message in #street-account confirming the run started,"
info "        then an end-of-run heartbeat ~5 min later (since this is a manual"
info "        --slack live test outside the AM cron window, the runner will"
info "        complete one full duration unless you stop it from the Actions UI)."
