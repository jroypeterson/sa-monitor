# StreetAccount Reverse-Engineering vs sa-monitor — Gap Report

**Date:** 2026-07-10
**Method:** Real StreetAccount emails (`service@streetaccount.com` → jroypeterson@gmail.com; ~200 per 120 days, ~40 on 2026-07-10 alone) cross-checked against `sa-monitor/` (PROJECT_BRIEF.md, README.md, template-library.md, PHASE3_PLAN.md, `src/` tree).
**Ground truth for "BUILT":** `src/` contains only `halt_monitor.py`, `feeds/` (nasdaq, nyse), `news/` (PRN/BW/GNW wire + cache), `calendars.py`, `enrichment.py`, `template.py`, `slack.py`, `dedup.py`, `state.py`, `coverage.py`, `reason_codes.py`. There is **no `src/events/`, no earnings module, no digest generator**. Live surface = trade halts/resumes + calendar "Note:" context + press-release cross-ref. Everything else is documentation.

---

## A. Observed StreetAccount email taxonomy (2026-07-10 inbox)

Subject grammar (confirmed live): `SA: <TICKER|^CODE>[. Also: <more>][, others] [<Headline>]`, with prefix variants `Revised: SA:` and headline-internal `Follow-up:` / `CORRECTION:`, `+TICKER` for pre-IPO names (e.g. `+APMD`, `+OPENAI`), and foreign suffixes (`.JP .HK .LN .FP .DC .NA .GR .SW`). Every body opens `HH:MM ET M/D/YY [StreetAccount]`.

### Family 1 — Single-stock event alerts (ticker-primary, portfolio-tagged)

| Type | Subject pattern | One-liner |
|---|---|---|
| Halt / resume / Note / cross-ref / Follow-up / CORRECTION / ADR | `SA: VRDN [… halted, news pending]` etc. | The halt cycle (template-library §3–§9); not directly observed 07-10 but extensively captured previously |
| FDA approval (initial + `Follow-up:` restatement) | `SA: MRK. Also: … PFE [FDA approves Keytruda and Keytruda QLEX …]`; `SA: SAN.FP. Also: BX [FDA approves Sarclisa Escena …]` | Regulatory decision alert; fires as a 2–4 email sequence; foreign primary tickers occur |
| Clinical data readout | `SA: 9969.HK. Also: ZBIO [InnoCare announces Phase Ib/IIa … Phase IIb meets endpoints]` | Trial readout, incl. foreign-listed issuers with US-listed `Also:` read-across names |
| M&A / takeover interest (media-sourced) | `SA: CNMD [CONMED explores sale amidst takeover interest - Bloomberg]` | Standalone rumor/leak alert with source attribution — **no halt involved** |
| M&A mechanics | `SA: UCB [… announces election deadline for Peach State merger …]` | Deal-process housekeeping on pending transactions |
| Legal / general corporate news | `SA: AAPL. Also: +OPENAI [Apple files lawsuit against OpenAI … - Bloomberg]` | Litigation, governance, misc. corporate events |
| Corporate disclosure | `SA: 1093.HK. Also: AZN.LN [CSPC discloses receipt of $25M R&D milestone payment …]` | Material-event / 8-K-equivalent disclosure summaries |
| Move explainer | `SA: JAZZ. Also: ALKS [Jazz Pharmaceuticals trades higher following competitor CRL]` | Editorial attribution of an intraday move to a cause (incl. sympathy moves) |
| Analyst rating / target change | `SA: TWLO. Also: ^MEDIA [Twilio upgraded to buy from hold at Stifel]` | Very high frequency; upgrades/downgrades/initiations/target changes |
| Broker single-stock preview | `SA: NFLX. Also: ^MEDIA [JP Morgan preview of Netflix Q2 results]` | Sell-side note summarized pre-event |
| IPO / S-1 filing | `Revised: SA: +APMD. Also: … [Apnimed files IPO to list on Nasdaq - S-1]` | New-issue pipeline alert; uses the `+TICKER` pre-IPO grammar |

### Family 2 — Structured earnings-cycle (ticker-primary, StreetAccount-branded, portfolio-tagged)

| Type | Subject pattern | One-liner |
|---|---|---|
| **Consensus Metrics Preview (Wave 1)** | `SA: JPM [StreetAccount Consensus Metrics Preview - JPMorgan Chase Q2 Earnings]` | Pre-earnings structured consensus: line-item estimates w/ estimate counts, segment breakdown, quarter price history vs S&P/sector ETF, options-implied move, last-4-quarter moves, 20-quarter beat rates, call reminder. **Full body captured 07-10** |
| EPS/Sales print (Wave 2) | `SA: {T} [{Co} reports Q? EPS $X vs FactSet $Y [N est, $L-H]]` | First post-print alert (library §10); not in 07-10 sample (Q2 season starts 7/14) |
| Metrics Recap (Wave 3) | `[StreetAccount Metrics Recap - {Co} Q? Earnings]` | Segment KPIs vs FactSet (§11) |
| Transcript Intelligence (Wave 4, TI_EARN + TI_EVENT) | `[Transcript Intelligence: {Co} Q? Earnings]` | GenAI call summary (§12/§14) |
| Street Takeaways (Wave 5) | `[Street Takeaways - {Co} Q? Earnings]` | Sell-side synthesis + valuation + revisions (§13) |

### Family 3 — Sector digests (`^SECTOR`-primary)

| Type | Subject code | One-liner |
|---|---|---|
| Sector pre-market summary | `^HEALTHPRE` (also `^TECHPRE`, `^MEDIAPRE` observed) | Daily long-form sector brief (§20 shape); exists per sector, not just HC |
| Sector weekly recap | `^HEALTHWEEK`/`^HEALTHPOST`; `^BANKING`/`^BANKPOST` | Friday weekly wrap per sector — **not in the library at all** |
| Sector intraday move note | `SA: ^HEALTH, MRNA [Broad biotech weakness on Friday paced by Moderna]` | Editorial intraday sector color pegged to a mover |
| Sector earnings preview | `SA: ^BANKING [Q2 Earnings Preview (Banks)]` | SA's own sector-level preview into a reporting cluster |
| Broker sector preview | `SA: ^INDUSTRIALS [Goldman Q2 Homebuilders … preview]` | Sell-side sector note summarized |

### Family 4 — Market-wide digests

| Type | Subject code | One-liner |
|---|---|---|
| Daily market recap | `^MKTSUMM` | Close wrap (Dow/S&P/Nasdaq + drivers) |
| Weekly market recap | `^MKTSUMM, ^USWEEKSUMM` | Friday weekly wrap |
| Pre-market trading update | `^MKTSUMM, ^TRADSUMM` | Market-wide pre-open |
| Week ahead | `^WEEKAHEAD` (w/ `^OFFERINGS`, `^PREIPO`) | Forward calendar: earnings, macro, IPO/offering pipeline |
| ESG daily | `^ESG` | Daily thematic digest |
| Macro podcast | `^MACRO, ^PODCAST` | FactSet weekly audio recap |
| Weekend reads | `^EUPMREADS` | Curated journalism links |
| Regional news/digests | `^TTNCAN`, `^CANSUMM` | Canada (and other regions) top news + movers |

### Family 5 — Screener tables

| Type | Subject code | One-liner |
|---|---|---|
| Unusual option volume | `^OPTIONS` | Table of names with anomalous options activity |
| Unusual share volume | `^UNUSUAL` | Volume outliers |
| 52-week highs/lows | `^52WEEK` | New-extreme list (92 names on 07-10) |
| Regional movers | `^CANSUMM` | "Trading higher/lower" mid-morning tables |

### Family 6 — Weekly thematic trackers

| Type | Subject code | One-liner |
|---|---|---|
| Notable Drug Events | `^BIOEVENTS` | Weekly clinical/regulatory catalyst calendar (§18) — **confirmed live 07-10** |
| Activist summary | `^ACTIVIST` | Weekly activist-situations tracker |
| Thematic movers | `^ESG, ^TECHSECTOR, ^THEMES` | Weekly AI/theme movers |
| GLP-1 Rx Tracker | `^GLP1` | Weekly IQVIA Rx digest (§17) — spec'd; **not observed in the 07-10 (Friday) sample** — see §C |
| Earnings Scorecard | `^EARNSCORE` | Weekly FactSet Earnings Insight stats (§21) — not observed (season lull; expected to reappear from mid-July) |

---

## B. Coverage matrix — BUILT vs SPEC'D-ONLY vs ABSENT

"BUILT" only where `src/` + PROJECT_BRIEF confirm a live generator. Fleet routing per README/PHASE3_PLAN noted in the last column.

| # | Observed SA surface | Status | Evidence / notes |
|---|---|---|---|
| 1 | Halt — basic + resume | **BUILT** | `src/halt_monitor.py`, `src/template.py`; live on GH Actions, ~1,095-ticker universe |
| 2 | Halt — "Note:" catalyst context | **BUILT (partial)** | `src/calendars.py` + `src/enrichment.py` — earnings-day + investor-day/conference Notes only. SA's PDUFA-day and clinical-call Notes need catalyst/PDUFA calendars sa-monitor doesn't ingest |
| 3 | Halt — news cross-ref ("Follows … press release") | **BUILT (partial)** | `src/news/` PRN/BW/GNW ±60-min window, live. SA also cross-refs *journalism* leaks (FT/Bloomberg/Sky) — explicitly deferred (paywalled) |
| 4 | Halt — Follow-up substantive alert (§7) | **SPEC'D-ONLY** | The actual news bracketed by halt/resume. Wire substrate is live; generator never written. README lists it as an unbuilt Phase 2 slice |
| 5 | Halt — CORRECTION handling (§8) | **SPEC'D-ONLY** | Manual Slack-thread workaround today |
| 6 | Foreign/ADR halts (§9) | **BUILT (US-listed ADRs only)** | US feeds fire on NVO-style ADR halts; European local-listing halts (PHIA.NA, GMAB.DC) ABSENT — needs European exchange feeds |
| 7 | **Consensus Metrics Preview (Wave 1)** | **ABSENT** | No template section, no generator. Only passing mentions (§9 NVO cross-ref; PHASE3_PLAN §9 defers it). The 07-10 JPM capture is the first full body — the library's biggest missing template |
| 8 | EPS/Sales print (Wave 2, §10) | **SPEC'D-ONLY** | Routed to `earnings_agent` (idea #45); no SA-format generator exists there yet |
| 9 | Metrics Recap (Wave 3, §11) | **SPEC'D-ONLY** | Routed to `earnings_agent`; blocked on JP supplying the KPI list (note: sibling `earnings_kpi` project is a WIP KPI extractor for managed care — partial substrate) |
| 10 | Transcript Intelligence (Wave 4, §12; TI_EVENT §14) | **SPEC'D-ONLY** | Routed to `transcripts` (which has `transcript_highlights` LIVE — a durable-takeaways digest, not per-call TI in SA grammar) |
| 11 | Street Takeaways (Wave 5, §13) | **SPEC'D-ONLY / PARKED** | No free sell-side source; correctly parked |
| 12 | Trial readout (§15/§19) | **SPEC'D-ONLY** | Routed to `catalyst_watch` 2026-06-16 (PHASE3_PLAN superseded). catalyst_watch is LIVE as a *calendar*, not a real-time readout-alert wire — the real-time PR-wire classify→extract→alert lane exists nowhere |
| 13 | FDA approval (§16) | **SPEC'D-ONLY** | Same routing and same gap as #12. Confirmed live twice on 07-10 (MRK, SAN.FP) |
| 14 | ^BIOEVENTS weekly (§18) | **SPEC'D-ONLY** | catalyst_watch's daily calendar is the natural composition source; no weekly SA-grammar digest generator |
| 15 | ^GLP1 weekly (§17) | **SPEC'D-ONLY / DEAD END** | IQVIA data is institutional-priced; the library itself flags this. Not observed 07-10 |
| 16 | ^HEALTHPRE daily (§20) | **SPEC'D-ONLY** | Phase 5 skeleton; library itself recommends a slimmed version only |
| 17 | ^EARNSCORE weekly (§21) | **SPEC'D-ONLY** | Trivially generatable from FactSet Earnings Insight (public PDF) |
| 18 | Analyst rating / target changes | **ABSENT** | Not spec'd, no generator anywhere in the fleet. Among the highest-frequency SA types |
| 19 | M&A / takeover-interest alerts (standalone, media-sourced) | **ABSENT** | §5 covers only the *halt-follows-leak* case. The CNMD-style no-halt rumor alert is unmodeled; source is paywalled journalism |
| 20 | M&A mechanics (deadlines, election forms) | **ABSENT** | Low value to JP |
| 21 | Legal / general corporate news | **ABSENT** | Bloomberg-sourced; partially reachable via PR wire for company-issued items |
| 22 | Corporate disclosures (8-K-equivalents, milestone payments) | **ABSENT in sa-monitor** | edgartools MCP + EDGAR `material_events`/`live_filings` cover the SEC-side substrate; no alert lane built |
| 23 | Move explainers | **ABSENT in sa-monitor** | `portfolio_daily` has a why-moved panel (positions only, EOD); `sigma-alert` detects the move but doesn't explain it |
| 24 | IPO / S-1 pipeline (`+TICKER`, `^PREIPO`, `^OFFERINGS`) | **ABSENT** | Renaissance IPO API (already keyed, free tier) + EDGAR S-1 live filings = free substrate |
| 25 | Sector weekly recap (^HEALTHWEEK/^HEALTHPOST) | **ABSENT** | Not even in the template library — a genuine library blind spot |
| 26 | Sector pre-market (non-HC: ^TECHPRE, ^MEDIAPRE) | **ABSENT** | Out of scope by design (HC focus); fine |
| 27 | Sector intraday move notes / sector earnings previews | **ABSENT** | Editorial; low feasibility |
| 28 | Market recaps (^MKTSUMM daily/weekly), pre-market (^TRADSUMM) | **ABSENT in sa-monitor** | `macro_monitor` (releases + markets growth views) is the sibling that partially covers the need |
| 29 | ^WEEKAHEAD forward calendar | **ABSENT as a digest** | Substrate is nearly complete across siblings: catalyst_watch + reporting_calendar + analyst-days + macro calendars; no weekly composed digest |
| 30 | Screener tables (^52WEEK, ^UNUSUAL, ^OPTIONS) | **ABSENT** | `sigma-alert` (sigma moves, 10 buckets) + `Idea Generation` (dislocation screens) already cover JP's version of this need |
| 31 | ^ACTIVIST weekly | **ABSENT** | `13F Analyzer` is quarterly/13F; real-time activism needs 13D/G tracking (edgartools could) |
| 32 | ^ESG / ^THEMES / regional / podcast / weekend reads | **ABSENT** | Low value to JP; skip |
| 33 | **Portfolio-tag routing** (`alert for portfolio(s): …`) | **ABSENT as a mechanism** | sa-monitor uses one flat CM-derived universe + a sector tag on the alert. See §D |

**Honest summary:** of ~30 distinct SA surfaces observed or documented, **3 are built** (all in the halt family, two of them partial), **~12 are spec'd-only**, and **~15 are absent from both code and spec**. The build so far covers the *rarest* (though most time-sensitive) email type in the inbox: on the 40-email day sampled, **zero were halts** — the bulk were digests, ratings changes, earnings-cycle, and single-stock news.

---

## C. Template-library validation against the 2026-07-10 corpus

**Confirmed (library holds up):**
- §1 subject grammar — `SA:` prefix, `. Also:`, bracketed headline, `Revised:` prefix all confirmed verbatim.
- §2 universal body skeleton — the CNMD and JPM full bodies match exactly: header line w/ price, portfolio footer (`· {Name} ({TICKER})`), `Tickers mentioned…100-day news history` closing line, footer stripped.
- §16 FDA approval — confirmed live twice (MRK initial + `Follow-up:` restatement; SAN.FP), including the multi-alert sequence the library documents.
- §15/§19 readouts — the InnoCare email matches the readout grammar, and confirms foreign-primary-ticker readouts with US `Also:` read-across names.
- §18 ^BIOEVENTS — confirmed live ("expected for the week of 12-Jul"), same weekly cadence and subject shape.
- §20 ^HEALTHPRE — confirmed live same-day.
- §2 portfolio names — "JP Medtech/Tools/DX" and "Non-HC" both re-confirmed; consistent with the library's observed set (Biopharma, JP HC Svcs, JP Medtech/Tools/DX, Software, Non-HC, JP PA).

**Drift / gaps the library must fix:**
1. **`^CODE`-primary subjects are undocumented.** §1's grammar and all its examples are ticker-primary; roughly half of a real day's mail is `SA: ^CODE, ^CODE2, …` digest-primary (often multiple codes, sometimes mixed with tickers: `SA: ^HEALTH, MRNA […]`). The grammar needs a digest variant, and a registry of observed `^` codes (≥25 seen: ^HEALTH, ^HEALTHPRE, ^HEALTHPOST, ^HEALTHWEEK, ^BIOEVENTS, ^GLP1, ^EARNSCORE, ^MKTSUMM, ^USWEEKSUMM, ^TRADSUMM, ^WEEKAHEAD, ^OFFERINGS, ^PREIPO, ^OPTIONS, ^UNUSUAL, ^52WEEK, ^ACTIVIST, ^ESG, ^THEMES, ^TECHSECTOR, ^TECHPRE, ^MEDIA, ^MEDIAPRE, ^BANKING, ^BANKPOST, ^INDUSTRIALS, ^MACRO, ^PODCAST, ^EUPMREADS, ^CANSUMM, ^TTNCAN).
2. **`+TICKER` pre-IPO grammar is missing from §1** (`+APMD`, `+OPENAI`). Needed if any IPO/S-1 or private-company-mention lane is ever built.
3. **Consensus Metrics Preview (Wave 1) has no section.** The JPM 07-10 body is a complete capture: consensus w/ estimate counts per line item, segment estimates (NII FTE vs reported, IB fee breakdown, FICC/Equities), quarter-to-date price vs S&P 500 vs sector ETF, options-implied move (~3.8%), last-4-quarter print moves, 20-quarter revenue/EPS beat rates, and the conference-call reminder w/ webcast link. This should be added as a new locked section (call it §10a / Wave 1) — it is also arguably the single most useful earnings-cycle email for a fundamental investor because it arrives *before* the print.
4. **Sector weekly recap (^HEALTHWEEK/^HEALTHPOST) and market-wide recaps (^MKTSUMM family) have no sections.** Even if never built, the taxonomy claim ("recreates the *whole* editorial product") is overstated without them mapped.
5. **§17 ^GLP1 not observed on a Friday sample.** 2026-07-10 was a Friday and the tracker (spec'd as a "weekly Friday digest") did not appear in the ~40-email day. One day proves nothing, but before any Phase 4 work replicates it, verify the product still fires / is still in JP's alert preferences — don't build against a possibly-retired template.
6. **Minor doc inconsistency:** README's file map says "template-library.md (19 templates)"; the library's own status table lists 19 templates across sections numbered to §21, and the task-level shorthand "21 templates" floats around. Trivial, but worth normalizing since the library is the cross-phase contract.

**Nothing in the library is contradicted** by the 07-10 corpus — the drift is all omission, not error. The locked skeletons that could be checked (universal body, FDA sequence, portfolio footer) match byte-for-byte patterns.

---

## D. The portfolio-tag personalization mechanism

Every single-stock SA alert carries:

```
StreetAccount alert for portfolio(s):
   ·  JP Medtech/Tools/DX (CNMD)
```

What this reveals about the real product:

1. **Routing is per-named-portfolio, not per-flat-watchlist.** JP has configured at least 6–7 named portfolios inside StreetAccount (Biopharma, JP HC Svcs, JP Medtech/Tools/DX, Non-HC, JP PA, Software — per library §13/§14 — plus the two re-confirmed 07-10). SA evaluates each alert against *every* portfolio and stamps all matches; a multi-portfolio hit (e.g. VRTX in two buckets, PFE appearing under both partner contexts in the ARVN approval) renders as multiple footer lines. Digest emails are instead tagged `for news category:` (§21) — a second routing dimension.
2. **The footer is doing triage work.** When 40 emails land in a day, the portfolio line is how a reader instantly knows *which mental book* an alert belongs to — coverage bucket, not just "in universe." It also encodes counterparty spillover: the SLNO halt is tagged `Biopharma (NBIX, SLNO)` — the *rumored acquirer* is pulled into the tag.
3. **sa-monitor's current approximation:** one flat ~1,095-ticker universe (CM-derived) + a `Sector: {sector} / {subsector}` line on each alert. That is genuinely equivalent for the *filtering* function, and the CM sector tag already approximates the *labeling* function — arguably better sourced, since CM's `Sector (JP)` taxonomy is the single source of truth and the library itself notes SA's portfolio names are just JP's hand-maintained shadow of it.

**Should sa-monitor model named sub-portfolios?** A qualified yes — as **derived labels and priority tiers, not as separate universes**:

- **Don't** replicate SA's mechanism literally (N hand-maintained ticker lists). That reintroduces the drift problem CM read-only derivation was designed to kill.
- **Do** add a portfolio-style footer computed from data sa-monitor already has or can cheaply join: CM `Sector (JP)`/`Subsector (JP)` → bucket name (Biopharma / HC Svcs / MedTech-Tools-DX / Non-HC), **plus a position-state dimension** — whether the ticker is a live position (`portfolio_daily`'s broker CSVs / CM positions states / `notion_watchlist`'s reconciled watchlist) vs coverage-only. `· Position (CNMD) · MedTech/Tools/DX` is strictly more useful than SA's tag because SA doesn't know what JP owns.
- **Do** let the bucket drive *rendering priority*, not channel routing: position-tagged alerts get an attention marker (or a Slack mention), coverage-only alerts stay plain. One `#street-account` channel stays the right call (design decision §3.6 in PROJECT_BRIEF).
- This is small: a join in `src/coverage.py` (bucket map) + one extra Block Kit line in `src/slack.py`/`template.py`, plus a read of a positions export at session start. It also future-proofs every later generator, since the universal body skeleton (§2) already reserves the footer slot — every phase inherits it for free.
- **Caveat:** per memory, CM positions currently leak in public repos and sa-monitor is a **public** repo. If position state is rendered into alerts, keep the positions file out of the repo (fetch at runtime from a private artifact) — don't commit a positions-tagged log back.

---

## E. Prioritized roadmap — value × feasibility, build-here vs compose-from-sibling

Frame: JP is solo, part-time, HC-focused, automating signal-from-noise. The fleet decision (2026-06-15/16) that "the StreetAccount recreation is a distributed system" is correct and should be enforced: **sa-monitor's lane is real-time wire events; editorial/periodic products belong to the sibling that owns the data.** PHASE3_PLAN's build-vs-compose question is answered surface-by-surface below.

| Rank | Surface | Value to JP | Feasibility | Build where | Rationale |
|---|---|---|---|---|---|
| 1 | **Halt Follow-up alert (§7)** — the substantive news that the halt/resume bracket | High — today's #1 UX hole: alert says "halted, news pending," the *news* never arrives in Slack | **High** — the PR wire (`src/news/`) is already flowing in production; add match-after-halt + LLM summary (Haiku/Sonnet) + §7 rendering | **sa-monitor** (its exact lane) | Closes the loop on the surface already built; smallest distance from live code |
| 2 | **Consensus Metrics Preview (Wave 1)** | High — pre-print consensus + implied move + beat-rate history is decision-support *before* the event, HC names report constantly | **Medium-high** — earnings_agent already merges Finnhub+FMP consensus and owns `reporting_calendar.json`; options-implied move computable from free chains (Robinhood MCP / yfinance); beat-rate history from cached prints | **Compose: `earnings_agent`** (cross-post to #street-account) | All source data lives there; rebuilding consensus in sa-monitor would duplicate a production pipeline |
| 3 | **EPS/Sales print (Wave 2, §10) in SA grammar** | High during season | High — earnings_agent computes beat/miss today; this is a formatting layer (existing idea #45) | **Compose: `earnings_agent`** | Already decided; still unshipped — flag as stale hand-off |
| 4 | **Real-time trial-readout + FDA-approval alerts (§15/§16/§19)** | Very high for an HC investor | Medium — PHASE3_PLAN's classify→extract→render design is sound and the wire exists in sa-monitor; catalyst_watch owns the taxonomy but has **no real-time wire** | **Decide explicitly**: either catalyst_watch grows a wire consumer, or sa-monitor runs the classifier and hands events to catalyst_watch. The 2026-06-16 routing moved the lane but nobody built the real-time half — this is the biggest *orphaned* surface | Highest-value HC catalysts; currently JP learns of them only if a halt fires or a digest arrives next morning |
| 5 | **^BIOEVENTS weekly digest (§18)** | High — the forward catalyst map | High — catalyst_watch is LIVE with a daily provenance-ledger calendar; a weekly SA-grammar rollup is a formatting pass | **Compose: `catalyst_watch`** | Don't rebuild the calendar sa-monitor-side |
| 6 | **Portfolio/position footer (§D)** | Medium-high, cross-cutting | High — small join + render change | **sa-monitor** (and adopt in siblings' cross-posts) | Cheap; improves every current and future alert |
| 7 | **^WEEKAHEAD-style weekly forward digest** | Medium-high | High — reporting_calendar + catalyst_watch + analyst-days + macro_monitor calendars already exist | **Compose: new thin rollup** (natural home: catalyst_watch or focus_today) | Pure composition; zero new data sources |
| 8 | Analyst rating/target changes | Medium (high frequency, but JP already gets moves via sigma-alert and doesn't trade on ratings) | **Low-medium** — no clean free source; FMP's upgrades/downgrades endpoint is tier-gated (verify against Starter before planning); Finnhub free excludes it; scraping is fragile | Defer pending a source check | Don't start until a free/Starter-tier source is verified |
| 9 | IPO/S-1 pipeline (`+TICKER`, ^PREIPO) | Low-medium (HC IPOs occasionally matter, e.g. Apnimed) | High — Renaissance IPO API already keyed (free 120/mo) + EDGAR S-1 live filings | Compose: tiny lane, arguably inside catalyst_watch | Nice-to-have; cheap |
| 10 | ^EARNSCORE weekly (§21) | Low (macro color) | High — FactSet Earnings Insight is public | Compose: macro_monitor | 30-minute build whenever wanted; low priority |
| 11 | ^ACTIVIST weekly | Low-medium | Medium — needs 13D/G live tracking (edgartools `live_filings`); 13F Analyzer is quarterly | Defer / possible 13F Analyzer extension | Not core to HC thesis work |
| 12 | ^HEALTHPRE / sector weekly recaps / ^MKTSUMM | Medium feel-good, low marginal info | Low — full-fidelity is SA's editorial moat; library §20 itself says don't pursue | Slim version only, later, composed from focus_today + macro_monitor + hc_macro_policy | The library's own judgment is right — respect it |
| — | Street Takeaways (§13), broker previews, GLP-1 IQVIA (§17), Bloomberg/FT-sourced M&A-rumor alerts | — | **Dead ends** — paywalled sell-side research, institutional Rx data, paywalled journalism | Parked | Correctly parked; do not burn time here. GLP-1 only revisit if a cheap claims proxy (Symphony/GoodRx) is actually purchased |

**On the build-vs-compose question generally:** the 07-10 evidence strengthens the compose answer. The single-day inbox shows StreetAccount is ~80% periodic/editorial product and ~20% real-time wire events; JP's fleet already owns most of the periodic substrate (earnings_agent, transcripts, catalyst_watch, macro_monitor, portfolio_daily, sigma-alert). sa-monitor should stay the thin real-time layer and `#street-account` the shared destination. The failure mode to guard against is the one visible in rank 4: a surface gets *routed* to a sibling and then nobody builds it — routing decisions need an owner and a next-action, or they become quiet ABSENTs dressed as SPEC'Ds.

---

## F. Highest-leverage next build

**Build the halt Follow-up alert (§7) in sa-monitor, and in the same session file the Wave-1 Consensus Metrics Preview as a concrete spec'd hand-off to earnings_agent (using the JPM capture as the golden fixture).**

Rationale for the Follow-up alert as #1:
1. **It completes the only product sa-monitor actually ships.** Today a halt alert reads "halted, news pending" and the pending news never arrives in the channel — JP still has to go look. The Follow-up is the payoff of the whole halt lane.
2. **Shortest path from live code of any candidate.** The PR wire, ticker-keyed cache, dedup pattern, Slack renderer, and §7 golden captures (INSM, ARVN, CELC) all exist. Net-new: after a halt on ticker T, watch the existing NewsCache for T's next substantive release (extend the window past 60 min post-halt), summarize with a cheap model per MODEL_POLICY, render §7, thread it under the original halt message.
3. **It naturally carries the CORRECTION/resume audit trail** (§7's archive block = the halt→follow-up→resume chain sa-monitor already logs), knocking out a second spec'd-only gap (§8 handling can piggyback the same thread mechanism).
4. **It is unambiguously sa-monitor's lane** under the fleet decision — no build-vs-compose debate, no dependency on another project shipping first.

Second-priority (parallel, different repo): the Wave-1 preview in earnings_agent is the highest *new-information* surface — it's the one email type JP would genuinely miss most if SA vanished, Q2 season starts 7/14, and the 07-10 JPM body provides the locked template. But it belongs to earnings_agent, so it's a hand-off with a fixture, not sa-monitor's next commit.
