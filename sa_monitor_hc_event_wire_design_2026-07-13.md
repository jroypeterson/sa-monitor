# Design: Near-Real-Time HC Event Wire (FDA + Clinical Readouts) for sa-monitor

**Date:** 2026-07-13
**Author:** Fable (design only — not built)
**For:** a builder to start immediately
**Target repo:** `C:\Users\jroyp\Dropbox\Claude Folder\sa-monitor\`
**Deliverable:** an additive `#street-account` alert lane that fires when an FDA action or clinical-trial readout hits a name in the coverage universe.

---

## 0. TL;DR verdict (read this first)

**Build v1 as a PR-wire event lane, not an openFDA lane.** sa-monitor already fetches the PR Newswire / Business Wire / GlobeNewswire *health* RSS feeds every ~30s and already extracts tickers from each item via an exchange-prefix regex (`(NASDAQ: VRTX)`). A company announcing an FDA approval or a Phase 3 readout **puts its own ticker in its own press release** — so the "sponsor→ticker" problem the brief flags is *already solved for the fastest, highest-value path*. v1 = classify those already-fetched, already-ticker-tagged items by event type, filter to the covered universe, dedup, and post an SA-faithful alert.

- **openFDA `drugsfda` is NOT a real-time approval feed** — grounded below, its data lags days-to-weeks and is keyed by uppercase applicant short-names ("GENUS", "HIKMA"). It belongs in a **secondary confirmation/safety lane (session 2)**, where the sponsor→ticker resolver is genuinely needed. It is designed here but deferred.
- **Clinical-trial readouts have no clean structured feed** — ClinicalTrials.gov posts results months late. The only near-real-time source is the PR wire. v1 catches them there.
- **v1 is one-session-finishable (~2h)** because it reuses coverage + dedup + state + slack + the news poll wholesale and adds ~2 small modules. The sponsor→ticker resolver + openFDA lane is a **separate second session**.

---

## 1. v1 scope — which event types fire (ranked by value × feasibility)

Ranking uses: **value** = does a covered-name investor need to know within seconds; **feasibility** = is there a near-real-time, free, ticker-resolvable source.

| Rank | Event type | Value | Feasibility | v1? | Source | Why |
|---|---|---|---|---|---|---|
| 1 | **Clinical-trial topline readout** (Phase 1/2/3 met / missed) | Very high — binary, gap-risk | High **via PR wire** | ✅ **v1** | PRN/BW/GNW (already polled) | Only real-time source is the PR; ticker is in the PR. Template §15/§19 locked. |
| 2 | **FDA drug approval** (+ CRL) | Very high | High **via PR wire** | ✅ **v1** | PRN/BW/GNW | Company PRs its own approval/CRL with ticker embedded. Template §16 locked. Near-real-time. |
| 3 | FDA approval (confirmation) | Medium (dedup of #2) | Low real-time | ⛔ defer → session 2 | openFDA `drugsfda` | Data lags days-weeks; sponsor-keyed. Backstop, not primary. |
| 4 | Drug safety / recall / FAERS | Low-medium for covered large names | Low real-time | ⛔ defer | openFDA `enforcement`, MedWatch RSS | Lags; recalls rarely move covered names materially; firm-name keyed. |
| 5 | AdComm (advisory-committee) calendar | Medium | N/A (calendar, not event) | ⛔ defer → `catalyst_watch` | FDA AdComm calendar | This is a *scheduled-calendar* surface, not an event wire. Belongs in the existing `catalyst_watch` project, not here. |

**v1 fires exactly two event families, both from the PR wire sa-monitor already ingests:**
1. **Trial readout** — headline matches Phase-N + endpoint grammar (met / missed / topline).
2. **FDA regulatory action** — approval, Complete Response Letter (CRL), clearance (510(k)/PMA for medtech), or "issues press release on FDA approval".

Everything else is deferred with the reasons above. **A shipped 2-event lane beats a broad stub** — and these two are the highest-value HC surfaces the user lacks.

---

## 2. Exact feeds + endpoints (grounded — probed 2026-07-13)

### 2.1 v1 sources — the PR wire (already wired into sa-monitor)

Defined in `src/news/{prnewswire,bw,gnw}.py`, fetched each news poll (`NEWS_POLL_EVERY=6` → ~30s at 5s halt cadence). **No new fetch code needed for v1.**

| Source | URL (in code today) | Shape parsed → `NewsItem` | Ticker field |
|---|---|---|---|
| PR Newswire | `https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss` | `title`, `body` (HTML-stripped), `url`, `published_at` (ISO-UTC), `industries` (PRN `<industry>` tags), `tickers` | `tickers` extracted from `title+body` by `parsers.extract_tickers` (exchange-prefix regex) |
| Business Wire | `https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRVQ==` | same | same |
| GlobeNewswire | `https://www.globenewswire.com/RssFeed/industry/9576-Health-Care/...` | same | same |

- **Latency:** a press release appears in these RSS feeds within seconds-to-~1-2 min of crossing the wire — i.e. **genuinely near-real-time**, the property openFDA lacks.
- **Rate limits:** none enforced beyond politeness; sa-monitor already polls them every ~30s in production without issue. v1 adds **zero** new HTTP calls — it consumes items already fetched.
- **Fields v1 parses:** `NewsItem.title` (primary classification input), `NewsItem.body` (secondary), `NewsItem.tickers` (universe filter), `NewsItem.industries` (PRN `TRI`=Clinical Trials / `PDT` codes as a weak prior), `NewsItem.published_at` (alert timestamp + dedup freshness), `NewsItem.url` (dedup key + reference link).

**Grounded live check (2026-07-13, a Sunday — low volume):** across all three feeds, 41 items; the exchange-prefix ticker extractor works as designed. On a weekday earnings/readout day this feed carries dozens of covered-name FDA/trial PRs. The classifier (see §3) is what turns raw items into events.

### 2.2 Secondary source — openFDA (session 2, designed not built)

- **`https://api.fda.gov/drug/drugsfda.json`** — probed live: filter `search=submissions.submission_status_date:[YYYYMMDD+TO+YYYYMMDD]` (URL-encode the brackets as `%5B … %5D`). Returns `sponsor_name` (e.g. `"GENUS"`, `"HIKMA"`), `submissions[]` (`submission_type` ORIG/SUPPL, `submission_status` AP, `submission_status_date`, `submission_class_code_description`), `products[]` (`brand_name`, `active_ingredients[].name`).
  - **HONEST LATENCY:** response `meta.last_updated` was **2026-07-10** on 2026-07-13, and `drugsfda` is a **weekly-batch database** — a novel approval typically appears here **days to weeks after** it happens and after the company has already PR'd it. **Do not treat this as real-time.** Its only value is (a) confirming/enriching an approval already caught via PR, (b) catching an approval whose PR the wire feeds missed.
  - Most rows in a recent window are `SUPPL` (labeling/REMS), not novel approvals — the classifier must filter to `ORIG` + `submission_status=AP` (or first-approval supplements) to avoid noise.
- **`https://api.fda.gov/drug/enforcement.json`** — recalls; firm-name keyed; also batch-lagged. Deferred (rank 4).
- **FDA RSS** (timely, same-day, but company-name-not-ticker keyed):
  - Press releases: `https://www.fda.gov/.../press-releases/rss.xml` (probed OK — carries major approvals same-day).
  - MedWatch safety: `https://www.fda.gov/.../medwatch/rss.xml` (probed OK).
- **openFDA rate limit:** 240 req/min & 1,000 req/day **without** an API key; 120k/day with a free key. Session-2 lane needs ~1 call/session, so keyless is fine.
- **API key:** free at `https://open.fda.gov/apis/authentication/` — store in `.secrets/` per the environment-secrets convention if/when session 2 is built. Not needed for v1.

### 2.3 ClinicalTrials.gov v2 (probed — confirms the "no clean readout feed" caveat)

- `https://clinicaltrials.gov/api/v2/studies?query.term=AREA[LastUpdatePostDate]RANGE[YYYY-MM-DD,MAX]&fields=NCTId,BriefTitle,LeadSponsorName,OverallStatus,LastUpdatePostDateStruct,ResultsFirstPostDate` — works, keyed by `leadSponsor.name` (full legal names **and universities**, e.g. "University of Pittsburgh").
- **Why it's NOT a v1 readout source:** a status flip to `COMPLETED` or a `ResultsFirstPostDate` lands **months** after the company announces topline data by PR. CT.gov is a registry, not a news wire. Useful later only as a *catalyst-calendar* input (belongs in `catalyst_watch`), not an event wire. Confirmed deferred.

---

## 3. Sponsor→ticker resolution (the crux) — solved two ways

### 3.1 The key insight: v1 mostly sidesteps it

For the PR-wire path, the **ticker is already extracted** by `parsers.extract_tickers` from the exchange-prefix parenthetical the issuer writes into its own release (`(NASDAQ: VRTX)`, `(NYSE: PFE)`). So the v1 resolution rule is trivial and false-positive-safe:

> **v1 fire rule:** an item fires iff (a) it classifies as an FDA/trial event AND (b) at least one of its already-extracted `tickers` is in the covered `Universe`. Alert is attributed to that covered ticker. No name-matching, no fuzzy logic, no misattribution risk from name collisions.

This also **captures partner moves for free**: a small biotech's approval PR that names its large-pharma partner writes both parentheticals (`Arvinas … its partner Pfizer Inc. (PFE)` — real §16 capture), so both `ARVN` and `PFE` land in `tickers`; if `PFE` is covered, it fires. No subsidiary logic required for the PR path.

**Confidence:** HIGH by construction (the issuer self-identified the ticker). **False-positive rate:** near-zero — the only failure mode is the exchange-prefix regex matching a stray token, already capped at 8 chars and case-sensitive in `parsers.py`.

### 3.2 The real resolver — needed only for the openFDA/RSS path (session 2)

openFDA gives `sponsor_name` ("GENUS") and FDA press RSS gives a company name in prose — **no ticker**. Here the resolver is required. Design:

**Name index (built once at load from `Universe`):** for each covered ticker, compute a `normalized_name`:
```
normalize(name):
  lowercase
  strip a trailing legal/entity suffix set:
    {inc, incorporated, corp, corporation, co, company, ltd, limited, plc,
     llc, lp, holdings, group, sa, ag, nv, se, ab, oyj, asa, adr, ads,
     class a/b, the}
  drop punctuation; collapse whitespace
  → also keep token_set = set(remaining tokens)
```
Store `{normalized_name -> ticker}` and `{frozenset(distinctive_tokens) -> ticker}`.

**Alias / override table** — `data/sponsor_aliases.json`, hand-curated, the durable home for everything normalization can't do:
```json
{
  "schema_version": 1,
  "aliases": {
    "genentech": "RHHBY",
    "janssen biotech": "JNJ",
    "janssen pharmaceuticals": "JNJ",
    "hikma": "HIKMA-LN-or-blank",
    "boehringer ingelheim": null,
    "vertex pharmaceuticals": "VRTX"
  },
  "notes": "null value = known sponsor, deliberately NOT a covered ticker (suppresses match-attempts + noise). Subsidiaries map to the covered PARENT ticker."
}
```
This table is where **subsidiaries and FDA-applicant-name quirks** live (openFDA's "GENENTECH" → Roche `RHHBY`; "JANSSEN BIOTECH" → `JNJ`). It is the single mechanism for the subsidiary/partner case on the openFDA path.

**Matching rule for an incoming sponsor string `S`:**
1. `n = normalize(S)`.
2. **Alias exact hit** → its ticker (or `null` = suppress). Confidence **HIGH** (curated).
3. **Exact `normalized_name` hit** in the universe index → ticker. Confidence **HIGH**.
4. **Fuzzy** (stdlib only — `difflib.SequenceMatcher` ratio + token-set Jaccard; no new dependency):
   - candidate set = universe names with `token_set ∩ S_tokens` non-empty on a *distinctive* token (drop generic tokens: `pharma, pharmaceuticals, therapeutics, bio, sciences, health, medical, labs`).
   - keep a candidate only if `ratio ≥ 0.92` **AND** it is the **unique** candidate above threshold.
   - unique + above threshold → Confidence **MEDIUM**.
5. **Otherwise → NO MATCH → DO NOT FIRE.**

**False-positive guard (the "better to miss than misfire" rule):**
- **Never fire below threshold; ambiguity (≥2 candidates over 0.92) → drop, never guess.**
- **Every drop is logged** (`sponsor`, `normalized`, best candidate, score) to the run log so the miss stream feeds `sponsor_aliases.json` curation — misses convert to curated HIGH-confidence hits over time.
- The generic-token stoplist prevents "X Therapeutics" ↔ "Y Therapeutics" collisions.
- Session-2 default: **fire on HIGH only**; MEDIUM matches render to the log for review before you enable them.

**Where the alias table lives:** `sa-monitor/data/sponsor_aliases.json`, loaded by the resolver, version-controlled, hand-edited. Same "derived data + curated overrides" pattern the project already uses for the universe.

---

## 4. Where it lives + module plan

**Verdict: additive lane inside sa-monitor, not a new project.** It reuses `Universe` (coverage), `HaltTracker` + `state` (dedup/persistence), `slack` (#street-account Block Kit + retry), and — critically — the **news poll already running in `halt_monitor.run()`**. A new project would duplicate all of that. This is exactly the "additive feed mirroring `src/feeds/` shape" the brief anticipated, except the *fetch* is already done — v1 is a *consumer* of the existing news poll.

### New files (v1)

```
src/events/__init__.py
src/events/types.py        # HCEvent dataclass
src/events/classify.py     # NewsItem -> Optional[HCEvent]  (keyword classifier)
tests/test_classify.py     # table-driven, from template-library §15/§16/§19 headlines
```

### Modified files (v1)

```
src/dedup.py       # + hc_events_emitted: set[str]  (news_ids)
src/state.py       # persist/restore hc_events_emitted (additive field, schema stays v1)
src/slack.py       # + build_hc_event_blocks() / post_hc_event()
src/halt_monitor.py# + _emit_hc_events(...) called in the news-poll branch; + CLI --hc-events
scripts/ci_run.sh  # + --hc-events flag (behind DISABLE_HC_EVENTS opt-out)
```

### `HCEvent` (src/events/types.py)

```python
@dataclass(frozen=True)
class HCEvent:
    news_id: str          # == NewsItem.url (dedup key)
    symbol: str           # covered ticker this event is attributed to
    event_type: str       # "trial_readout" | "fda_approval" | "crl" | "clearance"
    direction: str        # "met" | "missed" | "n/a"
    headline: str         # NewsItem.title (SA-faithful, verbatim)
    source: str           # "prnewswire" | "businesswire" | "globenewswire"
    url: str
    published_at: str     # ISO-UTC
    phase: str = ""       # "1"|"2"|"3"|"" for trial readouts
    confidence: str = "high"  # high (PR-wire ticker) | medium (resolver)
    raw_industries: tuple[str, ...] = ()
```

### `classify(item: NewsItem) -> Optional[HCEvent]` (src/events/classify.py)

Precision-biased keyword rules validated against the **locked real headlines** in `template-library.md`:

- **trial_readout** — title matches `Phase\s*[123]` AND one of {`met (its|dual)? primary`, `did not meet|does not meet.*primary`, `topline`, `primary endpoint`, `achieves primary`}.
  - `direction = "missed"` if `did not meet|does not meet|failed to meet`; else `"met"` if `met .*primary|achiev`; else `"n/a"` (topline, direction TBD).
  - `phase` = the matched digit.
  - Real anchors: `"reports Phase 3 REVEAL-2 trial … met its primary endpoint"` (§19), `"reports Phase 2B CEDAR study … did not meet its primary or secondary efficacy endpoints"` (§15).
- **fda_approval** — title matches `FDA approves`, `receives FDA approval`, `issues press release on FDA approval`, `FDA grants approval`. Anchor: `"Arvinas issues press release on FDA approval of VEPPANU…"` (§16).
- **crl** — `Complete Response Letter` or `\bCRL\b` with `FDA`.
- **clearance** (medtech) — `FDA clearance|510\(k\)|PMA approval|De Novo`.
- Return `None` if no rule matches (no event → no alert, never a guess).

The classifier only proposes an event; **the universe filter + dedup live in the emit path**, mirroring how `_emit`/`_emit_followups` already separate concerns.

### `_emit_hc_events(...)` in halt_monitor.py — slots into the existing loop

In `run()`'s news-poll branch (after `news_cache.ingest(news_items)`, where `news_items` is the freshly-fetched list), add:

```python
if hc_events_enabled:
    _emit_hc_events(
        news_items, universe, tracker, log_path,
        stats=stats, slack_mode=slack_mode,
        slack_webhook_url=slack_webhook_url,
    )
```

`_emit_hc_events` logic (mirrors `_emit_followups`):
```
for item in news_items:
    ev = classify(item)                     # None → skip
    if ev is None: continue
    # v1 universe filter = already-extracted tickers ∩ Universe
    covered = [t for t in item.tickers if universe.get(t)]
    if not covered: continue                # (session-2: resolver fallback here)
    for symbol in covered:
        dedup_key = f"{item.news_id}|{symbol}|{ev.event_type}"
        if dedup_key in tracker.hc_events_emitted: continue
        meta = universe.get(symbol)
        render + post (slack_mode gating identical to _emit)
        if delivered: tracker.hc_events_emitted.add(dedup_key)
        state.save(tracker) happens in the existing per-poll save
```

Gating rules copied verbatim from `_emit`: `off` → stdout-is-delivery, `live` → mark only on post success, `dry-run` → render, never mark. Post-then-mark so a transient Slack failure retries next poll.

---

## 5. Dedup/state + Slack output

### Dedup key

`"{news_id}|{symbol}|{event_type}"` (news_id == the PR URL). One alert per (press release, covered ticker, event type), ever. Persisted in `HaltTracker.hc_events_emitted` (new `set[str]`), saved/restored by `state.py` as an **additive field** (older state files lacking it rehydrate to empty — exactly how `emitted_halts`/`followed_up` were added; schema_version stays 1).

Note: the news cache's `_seen_ids` dedups *ingest*; `hc_events_emitted` dedups *delivery* and survives restart. Both are needed — same split the halt path already uses (`seen_halts` vs `emitted_halts`).

### Slack alert — SA-faithful, per template §15/§16/§19

Single-section Block Kit mrkdwn (matches existing `build_halt_blocks` shape, `#street-account`, existing webhook + retry). Emoji marks event type.

**FDA approval (template §16):**
```
:pill: *SA:* `ARVN` — FDA approves Veppanu for ESR1M, ER+/HER2- advanced breast cancer
`12:48 ET 5/01/26`  ·  Sector: Biopharma / Biotech
<biotech triage CTA — reuse template.biotech_triage_cta for biotech subsector>
_source: businesswire press release · <url>_
```

**Trial readout — MET (template §19):**
```
:test_tube: *SA:* `VRDN` — Phase 3 REVEAL-2 met its primary endpoint (elegrobart, chronic TED)
`07:05 ET 5/05/26`  ·  Sector: Biopharma / Biotech
_source: prnewswire press release · <url>_
```

**Trial readout — MISSED (template §15):** identical shape, headline as-written (`did not meet primary endpoint`), emoji `:small_red_triangle_down:`.

**CRL:** emoji `:x:`, `Receives Complete Response Letter for …`.

Format rules follow the library: time+date `HH:MM ET M/DD/YY`, `Sector: {sector} / {subsector}`, headline **verbatim from the issuer** (SA reproduces issuer language). Reuse `_format_date_short`, `_format_time_hhmm`, `biotech_triage_cta`, `is_biotech` from `template.py`. v1 body = headline + source (the fact-dense multi-sentence §15/§19 body is a **later LLM enhancement**, explicitly out of v1 — same call the shipped §7 follow-up made: headline+source first, LLM body later).

**Channel:** `#street-account` (consolidated, per `slack.py` — all sa-monitor lanes share it). No new channel.

### Relationship to the existing §7 halt-follow-up

A covered name that halts *and* PRs an approval will (correctly) produce a halt alert, then either a §7 follow-up (if the PR lands in the ±60m halt window) or an HC-event alert. To avoid a near-duplicate: **if `news_id` was already delivered as a §7 follow-up for the same symbol, skip the HC-event** (check `tracker.followed_up` provenance / a shared delivered-news set). Simple guard, noted for the builder; the reverse (HC event with no prior halt — e.g. a readout that didn't trigger an LULD halt) is the main net-new value this lane adds.

---

## 6. Build plan + honest effort estimate

**Ordered steps (v1 — PR-wire lane only):**
1. `src/events/types.py` — `HCEvent`. (10 min)
2. `src/events/classify.py` — keyword rules + `classify()`. (30 min)
3. `tests/test_classify.py` — table-driven from §15/§16/§19 real headlines + negatives (boilerplate "FDA-cleared facility" must NOT fire). (25 min)
4. `HaltTracker.hc_events_emitted` + `state.py` save/restore (additive) + `reset()`. (15 min)
5. `slack.build_hc_event_blocks()` / `post_hc_event()`. (20 min)
6. `halt_monitor._emit_hc_events()` + wire into news-poll branch + `--hc-events` flag; stat counters. (25 min)
7. `scripts/ci_run.sh` — add `--hc-events` (opt-out `DISABLE_HC_EVENTS`). (5 min)
8. **Verify in-session** (per the "trigger, don't wait" convention): `python -m src.halt_monitor --once --hc-events --slack dry-run --news-cross-ref` against live PR wire on a weekday; confirm a real covered readout/approval renders. Add a fixture-replay `--once` over a saved PR-wire capture so it's deterministic. (20 min)

**Total ≈ 2h 10m → yes, v1 is ONE-session-finishable**, because fetch/coverage/dedup/state/slack all exist. Keep openFDA + the sponsor resolver (§3.2) **out** of session 1 — that's a clean second session (build `resolver.py` + `sponsor_aliases.json` + `src/feeds/openfda.py` + a slow per-session poll; ~2-3h with alias curation).

**Top 2 risks:**
1. **Classifier precision.** False positives (a PR with "FDA" in boilerplate) create noise; false negatives (unusual readout phrasing) miss the event. *Mitigation:* precision-biased rules validated against the locked real headlines, a negative-test set, and a dry-run backtest over recent captures before going live. Start strict, loosen from the miss log.
2. **PR-wire coverage gaps.** The three health RSS feeds don't carry every covered name's PR (some issuers use other wires; feeds can truncate), and the exchange-prefix extractor misses PRs lacking the `(EXCH: TKR)` parenthetical. *Mitigation:* accept as a known miss (documented, like the AM→PM gap); the session-2 openFDA lane backstops approvals; log classified-but-no-ticker items so coverage holes are visible.

---

## 7. Feasibility caveats (set expectations honestly)

- **openFDA is not real-time.** `drugsfda` lagged to 2026-07-10 on 2026-07-13 and is a weekly batch; it will never beat the company's own press release. It is a confirmation/backstop, not the wire. Any expectation of "openFDA tells me the second a drug is approved" is wrong — the PR wire does that.
- **No clean clinical-readout feed exists.** ClinicalTrials.gov posts results months late; the near-real-time truth is the PR wire. v1's readout coverage is exactly as complete as the PR-wire coverage — good for names that PR through PRN/BW/GNW, blind to those that don't.
- **v1 depends on the issuer embedding its ticker** in the release (they almost always do). Where they don't, v1 can't attribute — that's the session-2 resolver's job, and even then only at HIGH confidence.
- **Bodies are headline-only in v1.** The fact-dense §15/§19 efficacy-table body is an LLM enhancement, deliberately deferred (mirrors the shipped §7 follow-up decision). v1 delivers the *signal* (what happened, which ticker, met/missed) — the reader opens the PR for the table.
- **Safety/recalls and AdComm calendar are out** — the former low-value/lagged, the latter a calendar surface that belongs in `catalyst_watch`, not an event wire.
- **False-positive philosophy is "miss over misfire"** throughout: the universe filter is exact-ticker (v1) or HIGH-confidence-only (session 2); ambiguous never fires. A wrong-ticker alert costs more trust than a missed one.

---

## 8. One-paragraph brief for the builder

Add an `src/events/` lane that consumes the PR-wire `NewsItem`s sa-monitor already fetches each news poll. `classify.py` turns an item into an `HCEvent` (trial_readout / fda_approval / crl / clearance) by keyword; `_emit_hc_events` in `halt_monitor.py` filters to items whose already-extracted `tickers` are in the covered `Universe`, dedups by `news_id|symbol|event_type` in a new persisted `HaltTracker.hc_events_emitted` set, and posts an SA-faithful single-section Block Kit alert (templates §15/§16/§19) to `#street-account` — reusing `slack.py`, `state.py`, `coverage.py`, and the existing slack_mode gating verbatim. Ship it behind `--hc-events` (opt-out in `ci_run.sh`), verify with `--once --slack dry-run` against the live wire plus a fixture replay, and leave openFDA + the `data/sponsor_aliases.json` resolver for a second session.
```
```
