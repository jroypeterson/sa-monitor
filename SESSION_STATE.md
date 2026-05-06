# sa-monitor — Session State (updated 2026-05-06)

**STATUS: Deployed to production. Repo public at `jroypeterson/sa-monitor`. AM/PM/watchdog crons live. Only remaining item is the 1-day live acceptance test against Gmail SA halts.** See `README.md` for the full project overview going forward; this doc remains as the cross-session cliff-notes for non-deliverable side items.

## Quick resume

To pick this up in a new session, attach the original kickoff doc (`uploads/cowork-phase1-kickoff.md` if still available, or just point the new session at this folder) and say something like:

> "Continue sa-monitor build. State doc at `Claude Folder/sa-monitor/SESSION_STATE.md`. D1–D6 are done. Next is D7 (GitHub Actions workflow)."

The new session has everything it needs from this folder.

## What's done

| Deliverable | Artifact | Status |
|---|---|---|
| D1: Data sources doc | `phase1-data-sources.md` | ✅ Locked |
| D2: Coverage filter | `data/sa_monitor_universe.json` (554 tickers) + `scripts/build_universe.py` | ✅ Locked |
| D3: Template library | `template-library.md` (19 templates, all from real Gmail full-body captures) | ✅ Locked |
| D4: Halt feed prototype | `src/feeds/{nasdaq,nyse,types}.py`, `src/dedup.py`, `src/coverage.py`, `src/template.py`, `src/reason_codes.py`, `src/halt_monitor.py` | ✅ Built; 40+ tests passing; live feed run pending egress fix or local execution |
| D5: Slack delivery | `src/slack.py` + 12 tests | ✅ Built; live post verified by user (synthetic AAPL → #street-account) |
| D6: End-to-end runner | `src/state.py` (persistence) + 7 tests; failure-DM wiring + crash-DM + final-heartbeat all in `halt_monitor.py` | ✅ Built; 68/68 tests passing |
| D7: GH Actions workflow | `.github/workflows/halt-monitor-{am,pm,watchdog}.yml` + `scripts/ci_run.sh` (state-commit-back wrapper) | ✅ Built; YAML + shell syntax validated |
| D8: README.md | Project deployment runbook | ✅ Written; 222 lines covering setup, deployment, error handling, Phase 2 extension seams |

## What's left (non-build, requires Jason's hands)

| Item | Notes |
|---|---|
| ~~GH repo creation~~ | ✅ Done 2026-05-06. Repo public at `https://github.com/jroypeterson/sa-monitor`. Made public to use free Actions minutes (private repo would have billed ~$69/mo at the 8h/day workflow runtime). |
| ~~Repo secret config~~ | ✅ Done 2026-05-06. `SLACK_WEBHOOK_STREET_ACCOUNT` registered for Actions. |
| ~~Manual first-run trigger~~ | ✅ Done 2026-05-06. Smoke run confirmed checkout/Python/deps/main loop all green; cancelled mid-run since markets were closed. AM/PM workflows now accept `-f duration=<seconds>` for cheap manual smokes going forward. |
| **Acceptance test** | One full trading day of live operation. Cross-check vs Gmail SA halts: zero false positives required, ≥80% match rate vs SA on coverage names. Per kickoff §"Acceptance test": relaxed latency criterion if data sources don't physically support 30s. **Next scheduled cron**: 2026-05-07 13:25 UTC (AM session). |

## Phase 1 routing decisions (locked)

Recap so next session doesn't re-litigate:

1. **Universe filter**: Lenient Biopharma exclusion + blank-Subsector Biopharma exclusion → 554 tickers (138 Specialty/Generic + 26 Large Pharma + 142 MedTech + 106 HC Services + 132 non-HC).
2. **Slack channel**: Single consolidated `#street-account` channel for ALL sa-monitor alerts across Phases 1–5. Supersedes the kickoff's 5-channel split.
3. **Webhook**: Reused on the existing "Earnings Agent Bot" Slack app. Env var `SLACK_WEBHOOK_STREET_ACCOUNT`. Token file at `Claude Folder/.secrets/slack_webhook_street_account.txt`.
4. **Halt feeds**: Both Nasdaq RSS + NYSE CSV polled at 5s cadence, dedupe by `(symbol, halt_date, halt_time)`. No Polygon (free tier only for Phase 1).
5. **Reason-code emit filter**: Phase 1 emits `T1, T2, T5, T6, T12, H4, H9, H10, H11, M1, LUDP, LUDS, MWC1/2/3, MWCO, MWCQ`. Excludes `T8, M2, O1, IPO*` by default but logs them.
6. **Health reporting**: Per `Claude Folder/HEALTH_REPORTING.md` v1 — Block Kit format, end-of-run heartbeat to `#street-account`. Failure-DM threshold = 60 consecutive feed failures (~5 min).

## Outstanding environmental issues

1. **Cowork workspace egress allowlist** — Cowork bug, "All domains" toggle doesn't propagate to sandbox proxy. Workaround: run locally on Windows where egress is unrestricted. Not blocking deployment (production runs on GH Actions where egress is unrestricted).
2. **CM ticker mismatch GH issue** — drafted at `coverage-manager-issue-draft.md`, not yet filed:
   ```
   gh issue create --repo jroypeterson/coverage-manager \
     --title "Ticker/Company-Name mismatches in coverage_universe_tickers.csv (ADAP, LIAN, MNK, ZOM, FGEN)" \
     --body-file "C:\Users\jroyp\Dropbox\Claude Folder\sa-monitor\coverage-manager-issue-draft.md"
   ```
3. **Slack webhook in chat transcript** — old webhook URL leaked into a prior session's transcript via stack trace. Rotate at Slack app settings → Incoming Webhooks → Regenerate URL. After rotation, also update the GH Actions secret (`gh secret set SLACK_WEBHOOK_STREET_ACCOUNT --repo jroypeterson/sa-monitor` from `.secrets/slack_webhook_street_account.txt`).
4. **GitHub PAT** — fine-grained PAT in `Claude Folder/.secrets/gh_pat_claude_issues.txt`, also leaked into transcript when first pasted. Rotate before next session if conservative.

## Privacy posture (2026-05-06)

Repo is public, so commit history and code are world-readable. Steps taken to scrub personal info before going public:
- All 3 commits' author/committer fields rewritten to `19582261+jroypeterson@users.noreply.github.com` (force-push to main on a then-private brand-new repo with no collaborators — safe blast radius).
- Local git config for this repo set to the noreply alias so future commits stay clean automatically.
- User-Agent in `src/feeds/nasdaq.py` and `src/feeds/nyse.py` uses the `+URL` convention (`sa-monitor/0.1 (+https://github.com/jroypeterson/sa-monitor)`) instead of the real email — same pattern as Googlebot/Slackbot.
- `scripts/one_shot_deploy.sh` fallback updated to noreply alias.

## File map

```
sa-monitor/
├── SESSION_STATE.md              ← this file
├── phase1-data-sources.md        ← D1
├── coverage-manager-issue-draft.md  ← issue body, not yet filed
├── template-library.md           ← D3 (19 templates)
├── requirements.txt
├── data/
│   └── sa_monitor_universe.json  ← D2 output, 554 tickers
├── scripts/
│   ├── build_universe.py         ← D2 builder, runs against Coverage Manager exports
│   └── gh_issues.py              ← GH issue helper (uses .secrets/gh_pat_claude_issues.txt)
├── src/
│   ├── __init__.py
│   ├── coverage.py               ← Universe loader
│   ├── dedup.py                  ← HaltTracker
│   ├── halt_monitor.py           ← main runner (D4+D5+D6 wired)
│   ├── reason_codes.py           ← Nasdaq + NYSE halt code mappings
│   ├── slack.py                  ← Block Kit + webhook delivery
│   ├── state.py                  ← daily-rotated dedup persistence
│   ├── template.py               ← halt + resume rendering
│   └── feeds/
│       ├── __init__.py
│       ├── nasdaq.py             ← RSS parser + fetcher
│       ├── nyse.py               ← CSV parser + fetcher
│       └── types.py              ← HaltEvent dataclass
├── tests/
│   ├── __init__.py
│   ├── test_coverage.py          ← 5 tests
│   ├── test_dedup.py             ← 7 tests
│   ├── test_feeds.py             ← 8 tests using fixtures
│   ├── test_reason_codes.py      ← 9 tests
│   ├── test_slack.py             ← 22 tests
│   ├── test_smoke.py             ← 3 end-to-end synthetic tests
│   ├── test_state.py             ← 7 tests
│   ├── test_template.py          ← 9 tests
│   └── fixtures/
│       ├── nasdaq_rss_sample.xml
│       └── nyse_csv_sample.csv
└── state/                        ← runtime dedup state (created on first run)
    └── dedup_state_<YYYY-MM-DD>.json
```

68/68 tests passing as of pause. Re-verify with:
```
cd "C:\Users\jroyp\Dropbox\Claude Folder\sa-monitor"
pip install -r requirements.txt
python -m pytest tests/ -q
```

## Resume next

The natural next move is D7 — wiring up the GH Actions cron + watchdog pattern, mirroring `sigma-alert/.github/workflows/sigma-{open,midday,close,watchdog}.yml`. That's mechanical YAML + repo-secret setup, no live-feed dependency. After that, D8 (README), then the live 1-day acceptance test which can be done locally regardless of cowork egress status.
