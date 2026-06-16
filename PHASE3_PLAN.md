# Phase 3 Plan — Clinical/Regulatory Event Alerts

> **Status: PLAN (refocused after JP review 2026-06-15) — for final sign-off
> before build.** The earlier draft scoped the whole earnings cycle here; review
> distributed most of it to the projects that own the data (see Decisions below),
> leaving sa-monitor's Phase 3 as **clinical/regulatory event alerts only**.
> Template grammar is LOCKED in `template-library.md` §15–16.

---

## Decisions (JP review, 2026-06-15) — where each StreetAccount surface lives

The StreetAccount recreation is a **distributed system across the fleet**, not one
project. Each surface lives where its source data already lives; `#street-account`
is the optional consolidated destination.

| StreetAccount surface | Decision | Home | Rationale |
|---|---|---|---|
| Wave 2 — EPS/Sales print | **Out of sa-monitor** | `earnings_agent` | Already computes beat/miss vs consensus; just needs SA formatting (existing triage idea #45). Don't recreate it here. |
| Wave 3 — Metrics Recap (segment KPIs) | **Out of sa-monitor** | `earnings_agent` (later-stage) | Belongs with the earnings data. **JP will supply the specific KPI list he wants tracked**, then earnings_agent extracts them regularly. |
| Wave 4 — Transcript Intelligence (per-call) | **Out of sa-monitor** | `transcripts` | That project owns the corpus + already runs Claude summarization (`transcript_highlights`). Per-call TI is a second generator on the same corpus; can cross-post to `#street-account`. |
| Wave 5 — Street Takeaways (sell-side) | **Skip** (note as future) | — | No clean/free sell-side broker-note source. Revisit only if a sentiment source appears. |
| **Trial readouts + FDA decisions** | **BUILD HERE** | **`sa-monitor`** | Reuses sa-monitor's live Phase-2 news wire; it's a real-time market-event, same shape as halts. **This is sa-monitor's entire Phase 3.** |
| Investor/R&D-day takeaways (TI_EVENT, §14) | Out of sa-monitor | `transcripts` | Same transcript path as Wave 4 — TI_EVENT and TI_EARN share grammar; build alongside Wave 4. |

**Resulting identity:** sa-monitor = **real-time market-event monitor** — trade
halts (Phase 1–2) + clinical/regulatory catalysts (Phase 3). The editorial
earnings cycle is owned by `earnings_agent` + `transcripts`.

---

## 1. Scope — what sa-monitor Phase 3 builds

Two standalone, non-earnings-gated alert types, posted to `#street-account`:

| Alert | Fires when | Carries | Template |
|---|---|---|:--:|
| **Trial readout** | a clinical-readout press release crosses the wire | drug, phase, indication, primary endpoint **met / not met**, key data points, halt/dissemination status | §15 |
| **FDA decision** | an approval / CRL / label press release crosses the wire | drug (brand + generic), full FDA indication string, partner, PDUFA-relative timing, companion-dx | §16 |

These are the **highest-value HC/biotech catalysts** and the cheapest Phase-3
slice — the wire that carries them is **already flowing in production** (Phase 2).

## 2. What we reuse (most of it already exists)

Phase 2's news layer (`src/news/`) already, in production:
- **Fetches** PR Newswire + Business Wire + GlobeNewswire RSS (`prnewswire.py`,
  `bw.py`, `gnw.py`) on a ~30s cadence inside the halt loop.
- **Parses** each item to a `NewsItem` (title, body, link, pubdate, **extracted
  tickers** via `parsers.extract_tickers`).
- **Indexes** by ticker with a rolling window (`NewsCache`), already de-duping items.

So the substrate — a stream of ticker-keyed press releases — is **done**. Phase 3
only adds: classify → extract → render → dedup-as-events → deliver.

## 3. The build (4 net-new pieces)

**A. Classifier** — `src/events/classify.py`, two-stage to keep LLM cost down:
  1. **Cheap keyword/regex prefilter** on title+body. Trial readout signals:
     `primary endpoint`, `topline`, `met (its)? primary`, `did not meet`,
     `Phase 1|2|3`, `study (of|evaluating)`. FDA signals: `FDA approv`,
     `Complete Response Letter`/`CRL`, `PDUFA`, `BLA|NDA|sNDA|sBLA`, `label`.
  2. **LLM confirm + structured extraction** on prefilter hits only — emit
     `{event_type, drug_brand, drug_generic, phase, indication, endpoint_met:
     bool|null, partner, pdufa_date, ...}`. Model per `MODEL_POLICY.md`
     (Sonnet/Haiku, not Opus). A null/low-confidence verdict drops the item.

**B. Templates** — `src/events/template.py`: render §15 (readout) + §16 (FDA) in
  SA grammar, with sa-monitor's improvements carried from Phase 1 (CM sector tag +
  portfolio footer from `src/coverage.py`). Reuse the captured §15/§16 examples
  (DAZALS miss, ARVN approval) as golden fixtures.

**C. Event dedup** — one alert per real event. Reuse the Phase-1 dedup pattern,
  keyed by `(ticker, event_type, event_date)` (not the headline hash, so a
  Follow-up restating the same approval doesn't re-fire). `NewsCache` already
  de-dups raw items; this adds event-level idempotency across a multi-PR sequence.

**D. Trigger / cadence** — readouts + approvals fire BMO, intraday, **and after
  close** — partly *outside* the halt sessions. They are **not** 5s-latency-
  critical (minutes is fine). Recommend a **dedicated lightweight `events` CI
  workflow** polling the wire every ~10–15 min across a wider daily window
  (pre-market → evening), independent of the halt sessions. (Alternative:
  piggyback the in-session 30s news poll — rejected: misses pre-market/evening,
  the prime catalyst windows.)

## 4. The one decision that gates value — biotech

**Trial readouts and FDA approvals are overwhelmingly biotech** (DAZALS, ARVN,
the §15/§16 captures are all biopharma). But **Phase 1 deliberately excludes
biotech from the universe** (`build_universe.py` drops `Subsector == Biotech` +
blank-subsector Biopharma). So an events lane filtered to the current ~554-name
non-biotech universe would **miss most of the catalysts it exists to catch.**

Options:
- **(i)** Re-include biotech in the *whole* universe — also adds biotech **halt**
  noise (the reason it was excluded); couples two decisions.
- **(ii)** Give the **events lane its own biotech-inclusive universe** — halts stay
  non-biotech, events filter on a broader list. **← Recommended.** Cleanly decouples
  the lanes; biotech catalysts surface without changing halt behavior.
- **(iii)** Ship events non-biotech first — low value; mostly large-pharma/medtech
  approvals only.

**This is the call needed before building 3A.** Recommend (ii).

## 5. Build slices (each = module + fixtures + tests, ship/verify one at a time)

- **3A.1 — Classifier + templates**, fixture-driven (the captured §15/§16 PRs +
  a handful of negatives). No live posting. Proves classify→extract→render.
- **3A.2 — Event dedup + wire integration**, dry-run against the live wire
  (`--once --slack dry-run`) to eyeball precision before posting.
- **3A.3 — Cadence + delivery**: the dedicated `events` workflow + live post to
  `#street-account` + end-of-run heartbeat (per `HEALTH_REPORTING.md`).

Manual entrypoint alongside the scheduler (`python -m src.events --once
--slack dry-run`), per `feedback_manual_test_entrypoints`. Tests network-free,
fixture-based, like Phases 1–2.

## 6. Cost

The keyword prefilter means the LLM only sees genuine candidates (~a handful/day
across the universe), each ~200–500 tokens of extraction on a cheap tier →
negligible. No Wave-4-style transcript-summary cost lands in sa-monitor (that's in
`transcripts`).

## 7. Handed to siblings — tracking (filed in root `PROJECT_IDEAS.md`)

- **`earnings_agent`** — (a) SA-format EPS/Sales print (existing idea #45);
  (b) **new: Metrics Recap / KPI-extraction stage** — JP supplies the KPI list,
  earnings_agent extracts them each quarter. *Awaiting JP's KPI list.*
- **`transcripts`** — per-call **Transcript Intelligence** generator (TI_EARN +
  TI_EVENT, SA §12/§14 grammar) on transcript-land; reuses `transcript_highlights`
  extraction; optional cross-post to `#street-account`.
- **Wave 5 Street Takeaways** — parked; no sell-side source. Future enhancement
  if a sentiment/broker-note feed becomes available.

## 8. Open questions for JP (just to confirm before 3A)

1. **§4 biotech:** confirm option (ii) — an events-only biotech-inclusive universe
   (recommended), vs (i) whole-universe re-include, vs (iii) non-biotech first.
2. **§3D cadence:** OK to add a dedicated ~15-min `events` CI workflow (separate
   from the halt sessions)?
3. **Destination:** events → `#street-account` (consolidated), as assumed?
4. Anything to add to the trial-readout/FDA extraction fields beyond §1's list?

## 9. Non-goals (this slice)

- Earnings-cycle waves (routed to siblings — see Decisions).
- Consensus Metrics **Preview** (SA Wave 1) — later phase.
- Non-US / foreign-listed event coverage (same feed limit as foreign halts, §9).
- Pure-journalism (FT/Bloomberg) event sourcing — paywalled, out of scope.
