# Phase 3 Build Plan — Earnings Cycle + Clinical/Regulatory Events

> **Status: PROPOSAL — for review, not yet started.** This plan scopes the next
> phase of the StreetAccount recreation. The point of this doc is to get
> feedback on **(a) the architecture decision in §2** and **(b) the build
> sequencing in §5** before any code is written. Template grammar for everything
> here is already LOCKED in `template-library.md` §10–16.

---

## 1. What Phase 3 is

StreetAccount's single most valuable non-halt output is its **earnings-cycle
coverage**: for every covered company that reports, SA fires a *sequence* of
alerts as the event unfolds, plus standalone **clinical/regulatory event** alerts
(trial readouts, FDA approvals). Phase 3 recreates that, posted to `#street-account`.

The earnings cycle is four "waves" per company per quarter (`template-library.md`):

| Wave | Alert | Fires | What it carries | §ref |
|:--:|---|---|---|:--:|
| **2** | **Initial EPS/Sales Print** | T+~1 min after the release | Headline EPS + revenue vs FactSet consensus (N est, low–high), GAAP/non-GAAP, FY guidance raise/hold/cut | §10 |
| **3** | **Metrics Recap** | T+5–15 min | Segment-level KPIs the headline misses — revenue by segment vs consensus, organic growth, gross/operating margin by segment | §11 |
| **4** | **Transcript Intelligence** | T+1–2 h (after the call) | GenAI Q&A summary, Themes/Risks/Opportunities/Strategic-Adjustments, near/long-term guidance | §12 |
| **5** | **Street Takeaways** | T+2–24 h | Editorial reaction: share move, sell-side analyst commentary, consensus revisions | §13 |

Plus **standalone event alerts** (not earnings-gated):

| Alert | Trigger | §ref |
|---|---|:--:|
| **Trial readout** (primary endpoint met/missed) | a clinical-readout press release crosses the wire | §15 |
| **FDA approval / decision** | an approval/CRL press release crosses the wire | §16 |
| **Investor/R&D-day takeaways** (TI_EVENT) | a non-earnings call transcript lands | §14 |

(Wave "1" in SA's numbering is the pre-earnings *Consensus Metrics Preview*; it's
a stretch goal, not in this plan.)

---

## 2. The architecture decision (PRIMARY feedback item)

Phase 3 overlaps heavily with two sibling projects that **already exist and run**:

- **`earnings_agent`** (v12, live) — already pulls actual EPS/revenue, computes
  beat/miss **vs consensus**, applies EDGAR date auto-correction, and posts a
  daily earnings digest. It is ~80% of **Wave 2's data**.
- **`transcripts`** (live) — maintains the earnings-call **transcript library**
  (daily backfill); the sibling `transcript_highlights` already runs **Claude
  summarization** over them. Together they are most of **Wave 4's substrate**.

So the real question is **not "how do we build four earnings generators"** — it's
**"where should this functionality live?"** Three options:

### Option A — sa-monitor as a self-contained generator
sa-monitor re-sources everything (consensus, PR parsing, transcript summarization)
and posts to `#street-account`. **Rejected:** duplicates earnings_agent +
transcripts wholesale, creates two sources of truth for "what did company X
report," doubles maintenance.

### Option B — sa-monitor as an aggregator/router (thin)
sa-monitor sources **nothing new**. earnings_agent and transcripts publish
structured outputs to their `exports/` (the same pattern Phase 2 already uses to
read their calendars); sa-monitor **reformats those into the SA template grammar**
and posts them, in the right sequence, to `#street-account`. The siblings stay the
single source of truth for the underlying facts.

### Option C — hybrid (RECOMMENDED)
Reuse the siblings where the data already exists, build net-new only where it
doesn't, and keep sa-monitor as the **composition + SA-grammar + sequencing +
`#street-account` delivery** layer:

| Wave / alert | Source-of-truth | sa-monitor's job | Net-new build |
|---|---|---|:--:|
| Wave 2 EPS/Sales | `earnings_agent` (consensus, actuals, guidance) | reformat → SA grammar; near-real-time trigger | the **real-time print trigger** (§4) + the consensus **range** (N est, L–H) if earnings_agent lacks it |
| Wave 3 Metrics Recap | **none yet** — segment KPIs live only in the PR/8-K | parse the release exhibit, extract segment table | **all of it** — LLM extraction over PR/8-K text (hardest data) |
| Wave 4 Transcript Intel | `transcripts` (corpus) + Claude | per-call SA-grammar summary on transcript-land | the **per-call** (vs weekly) Claude pass in SA's Q&A/Themes/Guidance format |
| Wave 5 Street Takeaways | partial — share move (sigma/`portfolio_daily`), consensus revisions (FMP); **sell-side notes have no clean source** | compose share move + revision; *omit* true sell-side editorializing | a **reduced** takeaway (no broker-note synthesis) — see §3 |
| Trial readout / FDA | **Phase 2 news ingest already flowing** (`src/news/` polls PRN/BW/GNW) | classify the PR → generate event alert | a **classifier + template** on the existing wire (cheapest high-value slice) |

**Why C:** it respects the existing source-of-truth boundary (`feedback_published_artifacts`,
`feedback_cross_repo_patching`), avoids the Option-A duplication, but doesn't
contort everything into Option-B when the upstream data genuinely doesn't exist
(Wave 3 segment KPIs, Wave 5 sell-side).

**Decision needed from JP:**
1. Confirm Option C (hybrid) vs. a preference for thin-B / fat-A.
2. A deeper question C forces: **should the earnings *Wave 2 print itself* even
   live in sa-monitor, or should `earnings_agent` just post its result to
   `#street-account` directly in SA format** (triage idea #45 already proposes
   "replicate the StreetAccount format for earnings notifications" *inside
   earnings_agent*)? If #45 ships in earnings_agent, sa-monitor's Wave 2 becomes
   redundant and Phase 3 should focus on Waves 3/4/5 + events. **This overlap is
   the single most important thing to resolve before building.**

---

## 3. Per-wave reality check (difficulty + what's genuinely hard)

- **Wave 2 — EPS/Sales print.** *Data: mostly solved by earnings_agent.* The hard
  part is **latency**, not content — SA fires at T+1 min; earnings_agent runs as a
  daily batch. Phase 3 needs a near-real-time print trigger (§4). The consensus
  **range** `[N est, $L–$H]` must be confirmed available (FMP analyst-estimates
  has count + range on Starter tier; verify earnings_agent already carries it).
  **Difficulty: LOW–MED.**
- **Wave 3 — Metrics Recap.** *Data: not available upstream.* Segment revenue /
  organic growth / segment margins live only in the earnings **press release or
  8-K exhibit**, in company-specific table formats. Requires LLM extraction over
  the release text with a verification gate (numbers must reconcile to the
  headline). This is the **hardest data-sourcing problem in Phase 3** and the most
  likely to produce wrong numbers if rushed. **Difficulty: HIGH.**
- **Wave 4 — Transcript Intelligence.** *Substrate: transcripts + Claude exist.*
  Net-new is a **per-call** trigger (fire when a given ticker's transcript lands,
  not the weekly digest cadence) and a prompt that emits SA's exact section
  grammar (Q&A Summary / Themes / Risks / Opportunities / Strategic Adjustments /
  Guidance near+long). Reuses the `transcript_highlights` extraction pattern.
  **Difficulty: MED.**
- **Wave 5 — Street Takeaways.** *Data: partially impossible.* Share move is easy
  (sigma / `portfolio_daily` why-moved), consensus revisions are gettable (FMP
  estimate deltas), but the **sell-side analyst commentary** SA synthesizes from
  broker notes has **no clean/free source** (same wall as the FactSet
  corporate-profit idea). Recommend a **reduced Wave 5**: share-move + consensus
  revision + (optional) a Perplexity "what did the Street say" pass, explicitly
  labeled as not-broker-sourced. **Difficulty: HIGH (full) / MED (reduced).**
- **Trial readout / FDA event.** *Wire already flowing.* Phase 2 already polls
  PRN/BW/GNW every ~30s and ticker-keys them. Add a **classifier** (is this PR a
  trial readout? an FDA decision?) + the §15/§16 templates. Highest HC/biotech
  value, and it reuses the most existing plumbing. **Difficulty: MED.**

---

## 4. The cross-cutting problem: latency + scheduling

Phase 1 halts run on a **5-second intraday poll** inside AM (13:25–19:00 UTC) and
PM (19:05–21:30 UTC) sessions. **Earnings prints don't fit that window:** most
report **BMO (pre-market, ~before 13:30 UTC)** or **AMC (after close, ~after
20:00–21:00 UTC)** — partly *outside* the halt sessions. So Phase 3 needs its own
trigger strategy. Options:

- **(a) Dedicated earnings-window poller** — a new CI session (or two: pre-market
  + after-close) that, gated by `earnings_agent`'s `upcoming_events.json` calendar
  (we already fetch it), polls actuals every N minutes **only for names reporting
  that day**. Bounded, cheap, mirrors the halt-session pattern. **Recommended.**
- **(b) Piggyback the halt loop** — add an earnings check to the 5s tick.
  Rejected: wrong time windows, couples two concerns.
- **(c) Event-driven from earnings_agent** — earnings_agent already detects a
  fresh print; have it emit a lightweight signal sa-monitor reacts to. Cleanest if
  #45 (§2) is decided in earnings_agent's favor.

Transcript-Intelligence (Wave 4) and event alerts are **not** latency-critical at
the 1-min level — a 15-min poll of the transcript manifest / news wire is fine.

**Decision needed:** (a) vs (c) depends on the §2.2 call about where Wave 2 lives.

---

## 5. Proposed build sequencing (slices)

Deliberately **not** Wave 2→5 order — sequence by *value ÷ cost*, cheapest-high-
value first, foundational dependencies respected (everything cross-refs Wave 2):

1. **Slice 3A — Clinical/regulatory event alerts (trial readout + FDA).** Reuses
   the live Phase-2 news wire; only a classifier + two templates. Highest HC value,
   lowest marginal cost, no new scheduling. **Best first slice; de-risks the
   "classify a PR → emit SA template" pattern Phase 3 reuses everywhere.**
2. **Slice 3B — Wave 2 EPS/Sales print.** *Gated on the §2.2 decision.* Either
   (i) build the reformat+trigger in sa-monitor, or (ii) ship #45 in earnings_agent
   and have sa-monitor just relay. Foundational — Waves 3/4/5 inline it as the
   `*****Related comments from the archive` cross-ref.
3. **Slice 3C — Wave 4 Transcript Intelligence.** Reuses transcripts +
   transcript_highlights; per-call Claude pass in SA grammar. High standalone value
   (it's the richest read), not blocked on Wave 3.
4. **Slice 3D — Wave 3 Metrics Recap.** Hardest data (PR/8-K segment extraction);
   do after 3B proves the print pipeline and gives the headline numbers to
   reconcile against.
5. **Slice 3E — Wave 5 Street Takeaways (reduced).** Share move + consensus
   revision; defer/flag the sell-side gap. Lowest incremental value given the
   sourcing wall.

Each slice = one generator module + (where needed) a CI cadence + fixture-based
tests, following the Phase 1/2 module pattern. Ship + verify one slice before the
next (`feedback_verify_in_session`, `feedback_manual_test_entrypoints`).

---

## 6. Cost (LLM tokens)

Per `template-library.md` budgets: Wave 2 ~250–600 tok, Wave 3 ~150–400, Wave 4
~1000–2000 (heaviest), Wave 5 variable. Peak earnings load ~80–120 reports/day for
4–6 weeks/quarter. Wave 4 dominates. Mitigations: only generate for **universe
names** (already filtered ~554, biotech still excluded), reuse transcript_highlights'
extraction (don't re-summarize), and model-tier per the `MODEL_POLICY.md`
(summarization → Sonnet/Haiku, not Opus). A rough quarter-peak ceiling and a
chosen model tier should be set before 3C/3D.

---

## 7. Open questions / decisions needed from JP (the feedback ask)

1. **§2 — Option C (hybrid) confirmed?** Or do you want thin-B (sa-monitor never
   sources anything) or fat-A?
2. **§2.2 — Wave 2 home: sa-monitor vs earnings_agent (#45)?** *Most important.*
   This determines whether Phase 3 even includes Wave 2 or starts at Waves 3/4/5.
3. **Biotech:** Phase 1 excludes biotech from the universe. Trial-readout/FDA
   alerts (Slice 3A) are *most* valuable for biotech. Do we re-include biotech for
   Phase 3 events (the deferred Phase-2 work), or keep events to the current
   non-biotech universe at first?
4. **Wave 5 sell-side gap:** accept a reduced Wave 5 (no broker notes), attempt a
   Perplexity-sourced approximation, or drop Wave 5 entirely?
5. **Scheduling (§4):** OK to add a dedicated pre-market + after-close earnings
   session, or prefer the event-driven-from-earnings_agent route?
6. **Sequencing (§5):** is "events first, then Wave 2" the right value order, or do
   you want the earnings print (Wave 2) first because it's the daily backbone?

---

## 8. Non-goals (Phase 3)

- Consensus Metrics **Preview** (SA's pre-earnings Wave 1) — separate later phase.
- True sell-side **broker-note** ingestion (no clean source; see Wave 5).
- Foreign-exchange **earnings** for non-US-listed names (same feed-coverage limit
  as foreign halts, `template-library.md` §9).
- Real-time **sub-minute** guarantees on Wave 2 — target T+a-few-minutes, not T+1s.
- Phase 4 weekly data trackers (GLP-1 Rx, BIOEVENTS) and Phase 5 morning brief.
