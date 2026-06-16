# sa-monitor
> **Goal: a self-hosted, free recreation of StreetAccount's full editorial feed**, scoped to the user's coverage universe and delivered to Slack `#street-account`. StreetAccount (a paid FactSet product) publishes halt notes, earnings-cycle alerts, clinical/regulatory event alerts, and weekly data trackers; sa-monitor recreates that *signal* without the subscription. **Phase 1 (trade-halt feed) and Phase 2 (halt enrichment) are LIVE; Phases 3–5 (earnings cycle, clinical/regulatory events, weekly data products, morning brief) are spec'd but not yet built.**

- **Status:** live — **Phase 1–2 of 5** (halt feed + enrichment). See the phase roadmap below for what's built vs planned.
- **Runtime/trigger:** Python via GitHub Actions (AM session 13:25 UTC, PM session 19:05 UTC, weekdays; hourly watchdog)
- **Reads:** NYSE LULD CSV + Nasdaq halt RSS (5s poll) · Coverage Manager universe (`data/sa_monitor_universe.json`) · earnings-agent + analyst-days event calendars
- **Writes:** Slack `#street-account` (halt/resume) · `state/dedup_state_<date>.json` · `logs/*.jsonl` · `#status-reports` (heartbeat/failure)
- **Run:** `bash scripts/ci_run.sh am 20100` (or `python -m src.halt_monitor --slack live --duration …`)  ·  **Entry points:** `src/halt_monitor.py`, `scripts/ci_run.sh`, `src/slack.py`

Repo: `https://github.com/jroypeterson/sa-monitor` (public — runs on free GitHub Actions minutes).

## Vision & phase roadmap

sa-monitor recreates the *whole* StreetAccount editorial product, phase by phase. Every phase's output grammar is reverse-engineered from real captured SA emails and "LOCKED" in `template-library.md`; each phase then adds a generator module + a poll cadence in CI. The halt feed shipped first because it's the most time-sensitive and the cheapest to source.

| Phase | Surface (StreetAccount output recreated) | Template spec | Generator status |
|:--:|---|:--:|:--:|
| **1** | **Trade halts / resumes** (basic, Note-context, news cross-ref, resume, foreign/ADR) | ✅ Locked (§1–9) | ✅ **LIVE** |
| **2** | **Halt enrichment** — editorial "Note:" preface, press-release cross-ref, calendar context | ✅ Locked | 🟡 **Partly live** — cross-ref + calendar live; Follow-up generation, CORRECTION auto-handling, biotech re-inclusion not built |
| **3** | **Clinical/regulatory events** — trial readouts + FDA decisions | ✅ Locked (§15–16) | ❌ Not built — **next phase here; plan in `PHASE3_PLAN.md`** |
| **4** | **Weekly data products** — GLP-1 Rx Tracker (`^GLP1`), Notable Drug Events (`^BIOEVENTS`) | ✅ Locked (§17–18) | ❌ Not built |
| **5** | **Morning brief / weekly digests** | ◻️ Skeleton | ❌ Not built |

> **The earnings cycle is owned by sibling projects, not sa-monitor** (JP decision
> 2026-06-15): EPS/Sales print + Metrics Recap → `earnings_agent`; per-call
> Transcript Intelligence → `transcripts`; Street Takeaways → parked (no sell-side
> source). The StreetAccount recreation is a **distributed system** across the
> fleet, with `#street-account` as the optional consolidated destination.
> sa-monitor's lane is **real-time market events** (halts + clinical/regulatory
> catalysts). See `PHASE3_PLAN.md`.

**Current operational scope = Phase 1 + Phase 2.** Everything below this section documents the live halt feed unless a heading says otherwise. For the full Phase 1 routing decisions see `phase1-data-sources.md`; for the canonical SA template grammar every phase consumes see `template-library.md`; for the Phase 3 build plan see `PHASE3_PLAN.md`.

### What the live halt feed does (Phase 1)

1. **Polls** Nasdaq Trader Trade Halt RSS (`nasdaqtrader.com/rss.aspx?feed=tradehalts`) and NYSE Trade Halt CSV (`nyse.com/api/trade-halts/current/download`) every 5 seconds during market hours.
2. **Filters** halt events to the sa-monitor coverage universe: 554 tickers covering Healthcare Services, MedTech, Large Pharma + Specialty/Generic Pharma, plus all non-healthcare sectors. Biotech is excluded today; **re-inclusion is the first Phase 3 step** (JP decision 2026-06-15 — biotech will then be covered by both halts and events; see `PHASE3_PLAN.md` §4).
3. **Dedupes** by `(symbol, halt_date, halt_time)` across both feeds — the same halt event reported by Nasdaq and NYSE simultaneously emits once.
4. **Renders** halt + resume notifications using the sa-monitor template variant (sector tag from Coverage Manager taxonomy + raw exchange reason code, both improvements over SA's editorial output).
5. **Posts** to Slack `#street-account` channel using Block Kit format, plus a JSONL event log for audit.
6. **Persists** dedup state to disk (`state/dedup_state_<YYYY-MM-DD>.json`) so a runner restart mid-session doesn't re-fire previously-seen halts.
7. **Self-monitors** via failure DMs (after 60 consecutive feed failures ≈ 5 min), end-of-run health heartbeats, and a hourly watchdog workflow that recovers missed cron events.

## Quick reference

| Question | Answer |
|---|---|
| What channel? | `#street-account` (single consolidated channel for ALL sa-monitor alerts across Phases 1-5) |
| What tickers? | 554 in `data/sa_monitor_universe.json` — see filter rule below |
| What halt codes emit alerts? | `T1, T2, T5, T6, T12, H4, H9, H10, H11, M1, LUDP, LUDS, MWC1/2/3, MWCO, MWCQ`. Codes `T8, M2, O1, IPO*` are logged but not alerted. |
| What's the latency target? | ≤30 seconds vs SA's editorial publish; achievable with 5s polling per `phase1-data-sources.md` §4.3 |
| Where does state live? | `state/dedup_state_<YYYY-MM-DD>.json`, daily-rotated, atomic writes, 7-day retention |
| What if the runner crashes? | The failure DM fires after 60 consecutive failures; the watchdog re-triggers missed sessions hourly; the dedup state survives restarts |
| What if a halt is wrongly emitted? | Surface to user via Slack thread; manual intervention. CORRECTION-handling for Phase 2 |

## Setup

### Local

```bash
git clone git@github.com:jroypeterson/sa-monitor.git
cd sa-monitor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

Set the Slack webhook env var or write to `../.secrets/slack_webhook_street_account.txt`:

```bash
export SLACK_WEBHOOK_STREET_ACCOUNT="https://hooks.slack.com/services/..."
```

Generate the universe filter from Coverage Manager exports (one-time + after CM updates):

```bash
python scripts/build_universe.py
# Wrote .../data/sa_monitor_universe.json (554 tickers)
```

Run the monitor:

```bash
# Quick smoke (one poll, exit)
python -m src.halt_monitor --once

# Live during market hours, post to Slack
python -m src.halt_monitor --slack live --duration 23400 --log logs/local_run.jsonl

# Dry-run (render Block Kit but don't POST)
python -m src.halt_monitor --slack dry-run --once
```

### GitHub Actions deployment

The runtime deployment is two scheduled workflows + a watchdog, modeled on `sigma-alert/.github/workflows/sigma-{open,midday,close,watchdog}.yml`.

```
.github/workflows/
├── halt-monitor-am.yml       # Cron 13:25 UTC, runs 5h35m → ends 19:00 UTC
├── halt-monitor-pm.yml       # Cron 19:05 UTC, runs 2h25m → ends 21:30 UTC
└── halt-monitor-watchdog.yml # Hourly 14:00-21:00 UTC; recovers missed sessions
```

**Setup checklist (one-time, completed 2026-05-06):**

1. ✅ Repo created at `jroypeterson/sa-monitor` (public).
2. ✅ `SLACK_WEBHOOK_STREET_ACCOUNT` repo secret configured for Actions.
3. ✅ Workflows pushed; auto-scheduled.
4. ✅ AM workflow manually triggered for first-run smoke; setup steps green.

**Manual smoke test going forward.** The AM/PM workflows accept a `duration` input (seconds) on `workflow_dispatch`. Use a small value to exercise the runner without burning a full session:
```
gh workflow run "halt-monitor — AM session" -f duration=60
gh workflow run "halt-monitor — PM session" -f duration=60
```
Defaults preserve full session length (20100s AM, 8700s PM) when scheduled by cron. Watch `#street-account` for the end-of-run heartbeat.

**State persistence on Actions.** `scripts/ci_run.sh` commits `state/dedup_state_<YYYY-MM-DD>.json` and `logs/halt_monitor_<date>_<session>.jsonl` back to the repo at end-of-job (via shell trap). The next session reads the latest state via `actions/checkout` at job start. There's a 5-minute gap between AM (ends 19:00 UTC) and PM (starts 19:05 UTC) — this is a known halt-monitor blind spot during market hours; documented and accepted for Phase 1.

**EDT vs EST timing.** GH Actions cron is UTC-only and not DST-aware. The 13:25 UTC AM cron lands at 09:25 ET during EDT and 08:25 ET during EST. The pre-market early-start during EST is harmless (idle polling against quiet feeds). Same pattern as sibling sigma-alert.

**Self-hosted runner.** Defer until 5s poll cadence proves insufficient or GH Actions cron drift becomes unworkable. Documented as Phase 1.5 in `phase1-data-sources.md` §5.

## How to change which tickers are monitored

The universe is filtered from sibling project Coverage Manager. To change which tickers are watched:

1. Update Coverage Manager (the source of truth — sa-monitor is read-only against it).
2. Rerun `python scripts/build_universe.py` to regenerate `data/sa_monitor_universe.json`.
3. Commit and push. The next CI run picks up the new universe.

The filter rule is locked at:
- Drop `Subsector (JP) == "Biotech"`
- Drop `Sector (JP) == "Biopharma"` rows with blank Subsector

Both rules live in `scripts/build_universe.py`. To add/remove sectors from the watch list, edit `EXCLUDE_SUBSECTOR` or `EXCLUDE_BIOPHARMA_BLANK_SUBSECTOR` and rerun. See `phase1-data-sources.md` §6 for the rationale.

## How to handle errors

| Failure mode | What you'll see | What to do |
|---|---|---|
| One feed temporarily unreachable | Log line `nasdaq_rss fetch failed (N consecutive)`, but the other feed still emits | Nothing. Recovery announced via log when the feed comes back |
| One feed unreachable for >5 min | Slack DM `:x: feed nasdaq_rss has failed N consecutive polls` | Investigate the feed source; sa-monitor stays running on the other feed |
| Both feeds unreachable for >5 min | Two DMs (one per feed); the runner keeps polling | Likely a network issue at GH Actions or upstream; if persistent, check status page of nasdaqtrader.com / nyse.com |
| Slack POST fails | Per-event log line; `slack_posts_failed` counter increments in the run summary | Check webhook URL; possibly Slack workspace rate-limited |
| Runner crashes | Crash DM `:x: halt-monitor crashed` if Slack reachable; otherwise GH Actions UI shows red | Check Actions logs for stack trace; the watchdog will re-trigger the next scheduled session |
| Watchdog fires recovery | `:rotating_light: halt-monitor watchdog recovered missed run(s)` heartbeat in `#street-account` | Investigate why the original session didn't fire (GH cron drop, repo secret rotation, etc.) |
| Universe stale (CM exports newer) | Visible only on inspection of `data/sa_monitor_universe.json.source.cm_dataset_version` | Run `scripts/build_universe.py`, commit, push |

A CORRECTION halt fired by SA on a ticker we already alerted on (e.g., RGEN 11/19/25) is currently not auto-handled — Phase 2 work. For Phase 1, manual surface-back via Slack thread reply.

## Phase 2 — enrichment (slices 1 + 2A + 2B LIVE)

Phase 2 adds the SA editorial preface line on halt alerts. Two priorities:

**Cross-ref (highest priority — slice 2B):**
- `Follows PR Newswire press release: {title}` (when a PRN/BW/GNW press release for the ticker landed within the last 60 min)
- Implemented in `src/news/` + `src/enrichment.py`. News polled every ~30s (every 6th halt tick) from PR Newswire / Business Wire / GlobeNewswire RSS. Cache: rolling 60-min window keyed by extracted ticker.
- Enable with `--news-cross-ref`. CI enables by default; opt out via `DISABLE_NEWS_CROSS_REF=1`.

**Calendar-based "Note:" context (slice 1):**
- `Note ITGR is scheduled to report earnings this morning` (earnings same-day)
- `Note AFRM is hosting an investor day today` (analyst-day same-day)
- `Note WST is presenting at an investor conference today` (conference)
- Implemented in `src/calendars.py` + `src/enrichment.py`. Calendars are loaded from local JSON files at session start; pass paths via `--earnings-calendar` and `--analyst-days-calendar`.

Cross-ref always wins over calendar context — a coincident press release is more specific than "earnings today."

Calendar JSON schema (both):
```json
{ "schema_version": 1, "source": "<repo>", "generated_at": "<iso>", "events": [...] }
```

Earnings event keys: `ticker, event_date (ISO), event_hour (bmo|amc|""), tier, date_confirmed, call_datetime_utc, company_name`. Analyst-day event keys: `ticker, company_name, event_type (investor_day|analyst_day|rd_day|capital_markets_day|conference), start_date, end_date, multi_day, status`.

Both feeds are published by sibling repos (`earnings-agent`, `analyst-days`) to `exports/upcoming_events.json`. sa-monitor's CI fetches them at session start (see `scripts/ci_run.sh`).

Phase 2 follow-on slices (not yet built):
- Follow-up substantive alerts (the actual news content posted ~1-30 min after halt — template-library §7 subtype 5)
- Biotech re-inclusion in the universe (currently filtered out per Phase 1 design)
- CORRECTION-handling for SA's CORRECTION-halt edits
- Pure-journalism feeds (FT/Bloomberg/Sky News) — paywalled, deferred

For Phases 3-5 (earnings, weekly digests, morning brief), the template skeletons are all locked in `template-library.md` §10–§21. Each phase adds a new generator module + new poll cadence in CI.

## Health reporting

Per `Claude Folder/HEALTH_REPORTING.md` v1, every scheduled run posts an end-of-run heartbeat to `#street-account` (the consolidated channel for sa-monitor alerts and ops) showing:
- session label (am/pm)
- polls completed
- halts + resumes emitted
- Slack post success/fail counts
- fetch error count
- next expected run

The heartbeat fires from `_post_health_heartbeat()` in `src/halt_monitor.py` at end of every run regardless of success state. Status emoji follows the spec convention: `:white_check_mark:` (ok) / `:warning:` (partial) / `:x:` (error).

## Testing

```bash
python -m pytest tests/ -q
```

68 tests covering reason-code mappings, dedup logic, template rendering, feed parsers (using fixture XML/CSV), coverage-universe loading, Slack Block Kit construction, webhook resolution, and state persistence. Tests are network-free and complete in <1 second.

## File map

```
sa-monitor/
├── README.md                       ← you are here
├── SESSION_STATE.md                ← cross-session resume reference
├── phase1-data-sources.md          ← D1: routing decisions
├── template-library.md             ← D3: canonical SA template grammar (19 templates)
├── coverage-manager-issue-draft.md ← Pending GH issue body for CM ticker mismatches
├── requirements.txt
├── .gitignore
├── .github/workflows/
│   ├── halt-monitor-am.yml         ← Cron 13:25 UTC, AM session
│   ├── halt-monitor-pm.yml         ← Cron 19:05 UTC, PM session
│   └── halt-monitor-watchdog.yml   ← Hourly, recovers missed sessions
├── data/
│   └── sa_monitor_universe.json    ← Filtered ticker universe (D2 output)
├── scripts/
│   ├── build_universe.py           ← Regenerate universe from Coverage Manager
│   ├── ci_run.sh                   ← GH Actions wrapper (state-commit-on-exit)
│   └── gh_issues.py                ← GH issue helper for cross-project communication
├── src/
│   ├── coverage.py                 ← Universe loader + ticker metadata lookup
│   ├── dedup.py                    ← HaltTracker — halt-id-based dedup
│   ├── halt_monitor.py             ← Main runner (D4+D5+D6 wired)
│   ├── reason_codes.py             ← Halt-code → human-readable mappings
│   ├── slack.py                    ← Block Kit construction + webhook delivery
│   ├── state.py                    ← Persistent dedup state (daily rotation)
│   ├── template.py                 ← Halt + resume rendering
│   └── feeds/
│       ├── types.py                ← HaltEvent dataclass
│       ├── nasdaq.py               ← Nasdaq RSS fetch + parse
│       └── nyse.py                 ← NYSE CSV fetch + parse
├── tests/
│   ├── test_coverage.py            ← 5 tests
│   ├── test_dedup.py               ← 7 tests
│   ├── test_feeds.py               ← 8 tests (fixture data)
│   ├── test_reason_codes.py        ← 9 tests
│   ├── test_slack.py               ← 22 tests (mocked HTTP)
│   ├── test_smoke.py               ← 3 end-to-end synthetic tests
│   ├── test_state.py               ← 7 tests
│   ├── test_template.py            ← 9 tests
│   └── fixtures/                   ← Sample feed payloads
├── state/                          ← Runtime dedup state (created on first run, committed by CI)
└── logs/                           ← JSONL event logs (committed by CI for audit)
```

## Sibling projects

sa-monitor reads from but does not write to sibling projects:

- **Coverage Manager** (`../Coverage Manager/`) — read-only dependency. sa-monitor consumes `exports/universe.csv` + `exports/universe_status.json` to build its filtered universe. `build_universe.py` gates on CM schema **v3** (bumped from v2 on 2026-06-14, commit 565af1c).
- **sigma-alert** (`../sigma-alert/`) — pattern reference. sa-monitor's GH Actions structure mirrors sigma-alert's (cron + watchdog + state-commit-back).
- **earnings_agent** (`../earnings_agent/`) — Slack app reference. sa-monitor reuses the existing "Earnings Agent Bot" Slack app for the `#street-account` webhook.

For the cross-project artifact map, see `Claude Folder/DEPENDENCIES.md`.

## License

Personal project. No license granted; not for redistribution.
