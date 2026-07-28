# Project Brief — read this first (for reviewers, human or AI)

> 🚧 **Maturity: Work in progress.** This project is partially built / not yet in routine production use. Review it for **direction and approach, not production hardening** — don't over-invest in edge-case, test-coverage, or polish feedback. §2 (status) and §5 (gaps) mark what's intentionally unbuilt.

This file exists so a reviewer can (1) judge how close the project is to its
intended goal and (2) understand the key design decisions **before** giving
feedback. For mechanics — feed parsing, halt-code tables, CI layout, error
runbook, file map — see `README.md` (don't duplicate it here). For the Phase 1
routing decisions see `phase1-data-sources.md`; for the template grammar see
`template-library.md`.

> When reviewing, weigh findings against the **success criteria** and the
> **non-goals / accepted tradeoffs** below. Several "obvious improvements"
> (biotech coverage, sub-5s latency, a self-hosted runner) were deliberately
> deferred to a later phase. Say so if you think a deferred option is worth
> pulling forward, but engage with the stated rationale rather than re-proposing
> it cold.

---

## 1. Intended goal (the "why")

Give the user a **self-hosted, free recreation of StreetAccount's full editorial
feed**, scoped to the names he actually follows. StreetAccount (a paid FactSet
product) publishes halt notes, earnings-cycle alerts (EPS/Sales print → Metrics
Recap → Transcript Intelligence → Street Takeaways), clinical/regulatory event
alerts (trial readouts, FDA approvals), and weekly data trackers (GLP-1 Rx,
notable drug events). The user wants the *signal* of that whole product —
delivered to Slack `#street-account` in near-real-time, for his coverage
universe only, without the subscription and without the editorial noise/latency.

**This is a phased build.** The **trade-halt feed is Phase 1** — the most
time-sensitive and cheapest-to-source surface, so it shipped first; **Phase 2**
adds the editorial enrichment on halts. **Phases 3–5** (earnings cycle,
clinical/regulatory events, weekly data products, morning brief) are spec'd in
`template-library.md` but not yet built — see the roadmap table in `README.md`
and the Phase 3 build plan in `PHASE3_PLAN.md`. Everything in §2–§4 below
describes the **live Phase 1+2 halt feed**, which is the current operational
scope; §5 covers what's next.

Context: the user is a solo, part-time, healthcare-focused investor automating
"signal from noise." For the halt feed specifically, a halt on a covered name is
a high-value, time-sensitive event (LULD volatility, news-pending, regulatory).
The win is **catching it within ~30s, filtered to names he cares about, with
enough context attached (sector tag, reason code, and a coincident press
release) to triage without opening the terminal.**

## 2. Success criteria — and current status

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Catch halts/resumes on covered names in near-real-time | ✅ Done | Dual-feed (NYSE LULD CSV + Nasdaq halt RSS) 5s poll during market hours; ≤30s latency target per `phase1-data-sources.md` §4.3 |
| 2 | Filter to the user's coverage universe, not the whole tape | ✅ Done | ~554-ticker universe in `data/sa_monitor_universe.json`, filtered from Coverage Manager; non-universe halts dropped |
| 3 | Don't double-fire when both feeds report the same halt | ✅ Done | `HaltTracker` dedupes by `(symbol, halt_date, halt_time)` across feeds; `tests/test_dedup.py` (7) |
| 4 | Alerts carry actionable context, not just "halted" | ✅ Done | sa-monitor template = CM sector tag + raw exchange reason code (`src/template.py`, `src/reason_codes.py`); Phase 2 adds the cross-ref/calendar preface |
| 5 | Cross-reference a coincident press release ("Follows {source}…") | ✅ Done | Phase 2 slice 2B LIVE; PRN/BW/GNW RSS polled ~30s, ±60-min ticker-keyed window; `src/news/` + `src/enrichment.py`; cross-ref wins over calendar context |
| 6 | Survive a mid-session runner restart without re-firing seen halts | ✅ Done | Daily-rotated `state/dedup_state_<date>.json`, atomic writes, committed back by CI; `tests/test_state.py` (7) |
| 7 | Runs unattended and free | ✅ Done | GitHub Actions AM (cron 13:25 → hard end 19:00 UTC) + PM (cron 16:05 → hard end 21:30 UTC) weekdays + hourly watchdog; wall-clock session windows so a delayed cron can't slide the session past the close; `scripts/ci_run.sh` |
| 8 | No silent failures | ✅ Done | Failure DM after 60 consecutive feed failures (~5 min); end-of-run `health/v1`-style heartbeat regardless of outcome; watchdog recovers missed sessions |
| 9 | Universe stays in sync with the Coverage Manager source of truth | ✅ Done | Regenerated via `scripts/build_universe.py`; CM schema gate bumped v2→**v3** on 2026-06-14 (565af1c), so regeneration tracks CM's current exports |
| 10 | Cover the names the user actually trades | ✅ Done | HC Svcs / MedTech / Pharma + all non-HC sectors, and **biotech re-included 2026-06-16** (~1,095 tickers, was ~568) to feed the biotech catalyst/triage loop (root `biotech_catalyst_architecture_plan.md`) |

**Overall verdict: the Phase 1+2 goal is met — the halt feed is live, filtered,
deduped, context-enriched, and self-monitoring.** The one non-green row is a
deliberate scope decision (biotech, criterion 10), not missing core function.
The larger gap is between this slice and the *full* StreetAccount vision: Phases
3–5 (criteria for which aren't listed here) remain unbuilt — see §5 and
`PHASE3_PLAN.md`.

## 3. Key design decisions (and why)

1. **Two feeds, deduped by halt-id — not one "best" feed.** NYSE and Nasdaq each
   only fully cover their own listings, and both can report a cross-listed event.
   Polling both and deduping on `(symbol, halt_date, halt_time)` maximizes
   coverage while guaranteeing one alert per real event. The halt-id key (not a
   content hash) is what makes dedupe robust to per-feed formatting differences.
2. **5-second poll during market hours, not a webhook/stream.** Neither source
   offers a push API; 5s polling is the cheapest cadence that meets the ≤30s
   latency target. A self-hosted low-latency runner was explicitly **deferred to
   Phase 1.5** until 5s proves insufficient (`phase1-data-sources.md` §5).
3. **Free GitHub Actions, modeled on sibling sigma-alert.** Cron AM/PM sessions +
   an hourly watchdog that recovers dropped cron runs, with dedup state committed
   back to the repo so the next session resumes cleanly. Reuses a proven pattern
   rather than standing up new infra. Accepted cost: a 5-min AM→PM gap and UTC/DST
   cron drift (both documented in `README.md`, harmless in practice).
4. **News cross-ref with a ±60-min window, and it outranks calendar context.** A
   press release landing right around the halt is the single most explanatory
   signal, so "Follows {source} press release" beats the weaker "earnings today /
   investor day today" calendar note. The 60-min window balances catching the
   real trigger against false attribution.
5. **Read-only against Coverage Manager.** The universe is *derived* from CM, never
   authored in sa-monitor — change tickers in CM, regenerate, commit. Keeps a
   single source of truth and prevents universe drift between fleet projects.
6. **One consolidated `#street-account` channel** for all sa-monitor alerts *and*
   ops/heartbeats across all five planned phases, rather than a channel per phase.

## 4. Non-goals / accepted tradeoffs

- **Biotech is excluded in Phase 1** (filter drops `Subsector == "Biotech"` and
  blank-subsector `Biopharma`, `build_universe.py`). Biotech halts are frequent,
  binary, and need different handling; re-inclusion is explicit Phase 2 follow-on
  work. Don't read this as a coverage bug.
- **Not sub-second / not a self-hosted runner** in Phase 1 — 5s on free Actions is
  the deliberate cost/latency tradeoff (deferred to Phase 1.5).
- **No auto-handling of SA CORRECTION halts** (a halt later corrected on a ticker
  already alerted, e.g. RGEN 11/19/25). Phase 1 surfaces these manually via Slack
  thread reply; auto-correction is Phase 2.
- **Editorial follow-on content** (the substantive news posted minutes after a
  halt) and **paywalled journalism feeds** (FT/Bloomberg) are out of scope for
  Phase 1/2.
- **Single channel, single universe, single user** assumptions throughout.

## 5. Known gaps / candidate next steps (feedback most wanted here)

- **Phases 3–5 are unbuilt — this is the biggest gap between the project and its
  goal.** The halt feed is one surface of the StreetAccount product; the earnings
  cycle (Phase 3), clinical/regulatory events (Phase 3), and weekly data trackers
  (Phase 4) are all spec'd in `template-library.md` §10–18 with zero generators
  written. **Phase 3 is the proposed next build — see `PHASE3_PLAN.md`** (it leans
  heavily on sibling projects `earnings_agent` + `transcripts`, and raises a real
  "build here vs. compose from siblings" architecture decision).
- **CM schema v2→v3 bump** — ✅ RESOLVED 2026-06-14 (565af1c); `build_universe.py`
  now gates v3. (Was the live debt; no longer.)
- **PM-session reliability** — ✅ RESOLVED 2026-06-15 (ed5588b); fixed silent
  state-loss in `commit_state` + watchdog false-failure noise. The residual
  scheduling problem (GitHub delaying the PM cron ~2h so the session ran after
  the close it watches) is ✅ RESOLVED 2026-07-28 (triage #210): sessions are now
  pinned to a wall-clock END rather than a run length, and the PM cron moved
  19:05 → 16:05 UTC so it queues behind AM and starts the moment AM's
  19:00 UTC hard end frees the concurrency group. See README §"Session windows".
- **Biotech re-inclusion** (Phase 2 follow-on) — the largest halt-coverage expansion.
- **CORRECTION-halt auto-handling** (Phase 2).
- **The 5-minute AM→PM gap** is an accepted blind spot during market hours;
  worth a sanity check on whether any real halts have been missed in it.
- **Wake/cron-drift robustness** — UTC-only cron + the watchdog cover most of it,
  but the fleet-wide wake-time DNS race pattern is worth confirming here too.

## 6. How to evaluate

- **Mechanics / runbook / file map:** `README.md` (start there for *how* it works).
- **Entry points:** `python -m src.halt_monitor` (`--once`, `--slack dry-run|live`,
  `--news-cross-ref`); CI wrapper `bash scripts/ci_run.sh am 20100`;
  `scripts/build_universe.py` to regenerate the universe.
- **Core logic to scrutinize:**
  - dedupe correctness across feeds — `src/dedup.py` + `tests/test_dedup.py`
  - feed parsing against real-shaped fixtures — `src/feeds/{nasdaq,nyse}.py` +
    `tests/test_feeds.py`, `tests/fixtures/`
  - which halt codes alert vs. log — `src/reason_codes.py` (+ README table)
  - the Phase 2 news cross-ref window/precedence — `src/news/`, `src/enrichment.py`,
    `tests/test_enrichment.py`, `tests/test_news_*`
  - the CM coupling — `scripts/build_universe.py` (the v2 assertion) + `src/coverage.py`
- **Tests:** `python -m pytest tests/ -q` — **138 tests across 13 files**,
  network-free (fixture feeds + mocked HTTP), runs in ~1s. (Do not run live feeds
  while iterating; use `--slack dry-run --once`.)
- **Most useful feedback:** (a) dedupe/edge-case correctness when both feeds
  report the same event with slightly different timestamps; (b) whether the news
  cross-ref ±60-min window and its precedence over calendar context match how a
  trader actually wants attribution; (c) how to make the CM v2→v3 bump
  forward-compatible so this debt doesn't recur on the next CM schema change; and
  (d) whether biotech belongs in Phase 1 after all.
