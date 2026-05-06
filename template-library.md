# StreetAccount Template Library

**Project:** sa-monitor
**Authoritative reference for:** all sa-monitor generator modules across Phases 1–5
**Status (2026-05-05, v1):** Phase 1 critical halt subtypes (1–7) fully locked from real Gmail full-body captures via Claude in Chrome. Phase 2–3 templates 8–19 still queued for body capture.

---

## 0. How this document was produced

Bodies were captured by navigating Gmail in Chrome (via the Claude-in-Chrome MCP) and reading the rendered page text for each thread. The Gmail MCP's `get_thread` tool returns only message snippets (~250 chars) even with `messageFormat: FULL_CONTENT`, so it was insufficient for the multi-paragraph templates. Chrome rendering captures the full body verbatim.

For each Phase 1 halt subtype below, the skeleton matches at least 1 real captured body, with cross-checks against subtype variants where multiple captures were available.

---

## 1. Subject-line grammar (universal, locked)

```
SA: {PRIMARY_TICKER}[. Also: {SECONDARY_TICKERS}] [{HEADLINE}]
```

Variants observed:

| Variant | Example subject |
|---|---|
| Single ticker | `SA: VRDN [Viridian Therapeutics halted, news pending]` |
| Primary + secondary | `SA: VRDN. Also: 4547.JP, ZLAB [Viridian Therapeutics reports Phase 3 REVEAL‑2…]` |
| With sector code | `SA: ARVN. Also: ^HEALTH, PFE [Follow-up: Shares of Arvinas halted, news pending]` |
| Top Story flag | `SA: Top Story KALV. Also: [Chiesi to acquire KalVista…]` |
| Revised | `Revised: SA: INSP. Also: NYXH […]` |
| CORRECTION | `SA: RGEN [CORRECTION: Repligen Corp. shares have not been halted]` |

Headline is always bracketed `[...]`. Multiple secondary tickers are comma-separated after `Also:`.

---

## 2. Universal body skeleton (locked)

Every SA email body follows this pattern:

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Headline}{ ($last_price{±change})}
{optional: body paragraph(s) — 0–N sentences, varies by template}
{optional: Reference Link: {label}}
{optional: *****Related comments from the archive: <inlined prior-comment text, separated by * * * * *>}
StreetAccount alert for portfolio(s): · {Portfolio_Name_1} ({TICKER list}){[ · {Portfolio_Name_2} ({TICKER list})]…}
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

Followed by SA's email-level footer (contact info, copyright, unsubscribe link) — **not part of the alert template**; sa-monitor's parser strips these.

### Field encoding rules (verified)

| Field | Format | Notes |
|---|---|---|
| Time | `HH:MM` 24-hour, 2-digit minutes, `ET` literal | Always 24-hour even in PM |
| Date | `M/DD/YY` | Month single-digit when possible, day always 2-digit, year 2-digit |
| Header marker | `[StreetAccount]` | Literal |
| Price-only | `($14.06)` | Dollar sign inside the parenthesis |
| Price with change | `($10.27 +$0.37)` or `($57.84 -$1.09)` | Sign immediately before dollar sign, single space inside parens |
| Foreign currency | `(DKK 372.55 -DKK 0.50)` | Currency code precedes amount; observed in NOVO.B.DC ADR-related preview |
| Portfolio footer | `· {Name} ({Tickers})` separated by ` · ` (with spaces) | Multiple portfolios per alert when relevant. Names: Biopharma, Non-HC, JP Medtech/Tools/DX, JP Medtech/Biopharma, JP PA |
| Archive cross-ref marker | `*****Related comments from the archive:` | Five literal asterisks |
| Inlined prior comment separator | ` * * * * * ` (space-separated, surrounded by spaces) | Between adjacent inlined comments |
| News-history closing line | `Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}` | Always the final "alert" line before email footer |

---

## 3. Halt subtype 1 — Basic halt ✅ LOCKED

The simplest halt template — no body, no Note, no cross-ref.

**Subject pattern:**

```
SA: {TICKER} [{Company short name} halted, news pending]
```

**Phrasing variants for the headline** (observed across captures):
- `halted, news pending` (most common — VRDN, ARVN, ESPR)
- `shares halted; news pending` (KALV pattern)
- `trading halted; news pending` (TVTX pattern)
- `ADRs halted, news pending` (foreign-issuer pattern → see subtype 7)

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} halted, news pending (${last_price}{ ±change})
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

That's the entire alert body. No paragraph between headline and portfolio footer. The "body" is one line — same as the headline, with ticker prefix and price suffix.

**Two real captures (verbatim, full bodies):**

VRDN 2026-05-05 06:56 ET (`19df7c84e8945e0f`):

```
06:56 ET 5/05/26 [StreetAccount] VRDN Viridian Therapeutics halted, news pending ($14.06)
StreetAccount alert for portfolio(s): · Biopharma (VRDN)
Tickers mentioned in/related to this story; follow link for 100-day news history: VRDN
```

ARVN 2026-05-01 11:23 ET (`19de423852956b4a`) — shows the price+change variant:

```
11:23 ET 5/01/26 [StreetAccount] ARVN Arvinas halted, news pending ($10.27 +$0.37)
StreetAccount alert for portfolio(s): · Biopharma (ARVN)
Tickers mentioned in/related to this story; follow link for 100-day news history: ARVN
```

**Optional change suffix.** Appears whenever SA has intraday tape data — e.g., 11:23 ET (mid-session) shows `+$0.37`; 06:56 ET (pre-market) typically shows price only since the prior close suffices.

**Token budget:** ~25 tokens for body. Trivial cost.

**sa-monitor template (Phase 1 v0):**

```
SA: {TICKER} [{name} halted, news pending]
{HH:MM} ET {M/DD/YY} [{TICKER}] halted at ${last_price}, reason code [{CODE} - {description}]
Sector: {sector} / {subsector}
```

(We replace SA's editorial halt phrasing with the raw exchange feed reason code, which we have direct access to and SA does not surface.)

---

## 4. Halt subtype 2 — Halt with "Note:" context ✅ LOCKED

When SA has additional editorial context — typically because the halted ticker is tied to a known catalyst — they append a single "Note ..." sentence between the headline and the portfolio footer. The Note can include a `(see linked comment)` parenthetical that links into a `*****Related comments from the archive:` block.

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} halted, news pending (${last_price})
Note {context sentence}{[ (see linked comment)]}
[*****Related comments from the archive: {prior-comment text, may include several * * * * *-separated segments}]
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**"Note" content patterns observed:**
- Pre-earnings: `Note ITGR is scheduled to report earnings this morning`
- Pre-call (clinical results): `Note NKTR is holding a call today at 8:00ET to discuss topline results from its REZOLVE-AA phase 2b trial of rezpeg in AA (see linked comment)`
- Pre-readout (clinical): `Note CMPX is expected to announce topline secondary endpoints from Phase 2/3 COMPANION-002 study of tovecimig` (per snippet — full body to confirm)
- PDUFA-day: per v2.1 spec, `Note RYTM ... PDUFA goal date for Imcivree sNDA is tomorrow`

**Two real captures (verbatim):**

ITGR 2026-04-30 07:57 ET (`19dde405f6b27bd0`) — pre-earnings, no archive cross-ref:

```
07:57 ET 4/30/26 [StreetAccount] ITGR Integer Holdings halted, news pending ($83.67)
Note ITGR is scheduled to report earnings this morning
StreetAccount alert for portfolio(s): · JP Medtech/Tools/DX (ITGR)
Tickers mentioned in/related to this story; follow link for 100-day news history: ITGR
```

NKTR 2026-04-20 07:25 ET (`19daaa3e18af8616`) — pre-call, with cross-ref expanding to the prior call announcement:

```
07:25 ET 4/20/26 [StreetAccount] NKTR Nektar Therapeutics halted, news pending ($84.86)
Note NKTR is holding a call today at 8:00ET to discuss topline results from its REZOLVE-AA phase 2b trial of rezpeg in AA (see linked comment)
*****Related comments from the archive: 19-Apr-26 16:44 ET NKTR Nektar Therapeutics to hold conference call tomorrow (20-Apr) regarding 52-Week topline results for REZOLVE-AA Phase 2b study of Rezpegaldesleukin in Alopecia Areata ($84.86) To review 52-week topline results from the 16-week extension treatment period of the ongoing Phase 2b REZOLVE-AA clinical trial of investigational rezpegaldesleukin for severe-to-very-severe alopecia areata Monday, April 20, 2026 at 08:00 ET / 05:00 PT Live webcast link * * * * *
StreetAccount alert for portfolio(s): · Biopharma (NKTR)
Tickers mentioned in/related to this story; follow link for 100-day news history: NKTR
```

**sa-monitor design implication.** Generating the contextual "Note" requires cross-reference to: an earnings calendar, a clinical-events calendar, a PDUFA calendar, and a press-release wire. **This is explicit Phase 2 enrichment, not Phase 1.** Phase 1 emits the basic halt without Note context. The SA-equivalent enrichment lights up in Phase 2 when we ingest the news/PR wire and SEC 8-K cross-reference.

---

## 5. Halt subtype 3 — Halt cross-referenced to broken news ✅ LOCKED

When the halt comes AFTER a news leak (FT, Bloomberg, Sky News, etc.), SA injects a `Follows {source} report that ...` sentence and appends the full prior leak comment via the archive cross-ref.

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} halted, news pending (${last_price})
Follows {source-and-when} report that {summary} (see linked comment)
*****Related comments from the archive: {prior leak-comment text} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER list — often plus rumored counterparty})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

**Two real captures:**

SLNO 2026-04-06 06:56 ET (`19d626fca30e5a4c`) — FT weekend leak, with NBIX as counterparty:

```
06:56 ET 4/06/26 [StreetAccount] SLNO Soleno Therapeutics halted, news pending ($39.49)
Follows weekend FT report that Neurocrine (NBIX) was near a deal to buy Soleno for more than $2.5B (see linked comment)
*****Related comments from the archive: 05-Apr-26 23:28 ET SLNO Neurocrine near deal to buy Soleno Therapeutics for more than $2.5B - FT ($39.49) StreetAccount notes that Soleno's current market cap is $2.07B. * * * * *
StreetAccount alert for portfolio(s): · Biopharma (NBIX, SLNO)
Tickers mentioned in/related to this story; follow link for 100-day news history: NBIX, SLNO
```

TLRY 2026-03-02 08:52 ET (`19caed28d6e5d265`) — Sky News earlier-same-day leak:

```
08:52 ET 3/02/26 [StreetAccount] TLRY Tilray Brands halted, news pending ($7.87)
Follows earlier Sky News report that Tilray was close to an announcement of a deal to acquire BrewDog (see linked comment)
*****Related comments from the archive: 02-Mar-26 07:31 ET TLRY Tilray Brands close to announcing a deal to acquire most of BrewDog - Sky News (~6:00ET) ($7.87) * * * * *
StreetAccount alert for portfolio(s): · Biopharma (TLRY)
Tickers mentioned in/related to this story; follow link for 100-day news history: TLRY
```

**Source-attribution patterns observed:**
- `Follows weekend FT report that ...`
- `Follows earlier Sky News report that ...`
- (per v2.1) `Follows overnight Bloomberg report that ...`

**Phase 2 sa-monitor extension.** Detecting cross-refs requires a news/PR wire ingest (PR Newswire, Business Wire, GlobeNewswire) plus FT/Bloomberg headline ingest. Out of Phase 1 scope. Phase 2 will compose this directly from the wire feed.

---

## 6. Halt subtype 4 — Resume trading at HH:MM ✅ LOCKED

**Subject pattern:**

```
SA: {TICKER} [{Company} {will resume trading at HH:MM ET | shares to resume trading at HH:MMET}]
```

Phrasing variants:
- `will resume trading at {HH:MM} ET` (INSM pattern — note space before ET)
- `shares to resume trading at {HH:MM}ET` (TVTX/VRDN pattern — no space before ET)

These are interchangeable from SA's editorial side.

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} {will resume / shares to resume} trading at {HH:MM} ET (${last_price})
*****Related comments from the archive: {Full text of prior follow-up news comment} * * * * * {Full text of next-prior comment, e.g. earlier follow-up} * * * * * {Full text of original halt notice} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (INSM 2026-04-07 16:17 ET resume — `19d699807a8a67b9`):**

```
16:17 ET 4/07/26 [StreetAccount] INSM Insmed will resume trading at 16:30 ET ($163.03)
*****Related comments from the archive: 07-Apr-26 16:05 ET INSM Follow-up: Insmed announces Phase 2B CEDAR study of brensocatib in adults with moderate to severe hidradenitis suppurativa (HS) did not meet its primary or secondary efficacy endpoints ($163.03) INSM announced that the Phase 2B CEDAR study, which evaluated brensocatib (BRINSUPRI ) in adult patients with moderate to severe hidradenitis suppurativa (HS), did not meet its primary or secondary efficacy endpoints in either the 10 mg or 40 mg treatment arms. Brensocatib was well tolerated, with no new safety signals identified, including in the 40 mg arm, which is the highest dose Insmed has studied to date. Insmed will discontinue its development program of brensocatib in HS and intends to present these data at a future congress. At Week 16, study participants experienced a 45.5% and 40.3% reduction from baseline in total abscess and inflammatory nodule (AN) count in the brensocatib 10 mg and 40 mg arms, respectively, compared to a 57.1% reduction in the placebo arm. Treatment-emergent adverse event (TEAE) percentages during the 16-week placebo-controlled treatment period are available in the attached press release. INSM remains halted, pending dissemination. * * * * * 07-Apr-26 16:03 ET INSM Insmed announces Phase 2B CEDAR study of brensocatib in adults with moderate to severe hidradenitis suppurativa (HS) did not meet its primary or secondary efficacy endpoints ($163.03) * * * * * 07-Apr-26 16:01 ET INSM Insmed halted; news pending ($163.03) * * * * *
StreetAccount alert for portfolio(s): · Biopharma (INSM)
Tickers mentioned in/related to this story; follow link for 100-day news history: INSM
```

**Notice:** the resume notification's `*****Related comments` block inlines THREE prior comments — the substantive follow-up, an interim shorter follow-up, and the original halt. This is SA's halt-event audit trail. The chronology runs newest first.

**Resume timing note.** SA emits resume alerts ~10–15 minutes BEFORE actual resumption (16:17 ET alert for 16:30 ET resumption). NYSE LULD and Nasdaq publish a resume timestamp ahead of time too — sa-monitor will fire when that timestamp first appears in the feed (no separate processing needed).

**sa-monitor template (Phase 1 v0):**

```
SA: {TICKER} [shares to resume trading at {HH:MM} ET]
{HH:MM} ET {M/DD/YY} [{TICKER}] resume scheduled at {HH:MM} ET, originally halted at {HH:MM} ET ({elapsed_minutes}m halt)
Sector: {sector} / {subsector}
```

(We can compute halt-duration directly from exchange feed timestamps, value SA doesn't.)

---

## 7. Halt subtype 5 — Follow-up to halted news ✅ LOCKED (Phase 2 reference)

After a halt, when actual news crosses, SA emits a `Follow-up: ...` alert with substantive body content. **This is the editorial "real" alert that the halt + resume bracket** — Phase 2 sa-monitor will need to match this when we ingest the underlying PR wire / 8-K.

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} Follow-up: {Substantive headline} (${last_price})
{Body paragraph(s): 1–N sentences of fact-dense summary, no opinion}
[Reference Link: {label, e.g. "Press release"}]
*****Related comments from the archive: {Inlined prior-comment text including the original halt and any interim comments, separated by * * * * *} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio_1} ({TICKER list_1})[ · {Portfolio_2} ({TICKER list_2})]…
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

The body paragraph is the longest content in any halt-cycle alert — typically 3–8 sentences for trial readouts, 3–4 for FDA approvals, 4–6 for M&A. Sentences are fact-dense and avoid opinion.

**Three real captures (verbatim — body paragraph isolated):**

INSM 2026-04-07 16:05 ET (`19d698cb16e48e49`) — Phase 2B trial MISS:

> INSM announced that the Phase 2B CEDAR study, which evaluated brensocatib (BRINSUPRI ) in adult patients with moderate to severe hidradenitis suppurativa (HS), did not meet its primary or secondary efficacy endpoints in either the 10 mg or 40 mg treatment arms. Brensocatib was well tolerated, with no new safety signals identified, including in the 40 mg arm, which is the highest dose Insmed has studied to date. Insmed will discontinue its development program of brensocatib in HS and intends to present these data at a future congress. At Week 16, study participants experienced a 45.5% and 40.3% reduction from baseline in total abscess and inflammatory nodule (AN) count in the brensocatib 10 mg and 40 mg arms, respectively, compared to a 57.1% reduction in the placebo arm. Treatment-emergent adverse event (TEAE) percentages during the 16-week placebo-controlled treatment period are available in the attached press release. INSM remains halted, pending dissemination. Reference Link: Press release

ARVN 2026-05-01 12:24 ET (`19de45bccedc93ff`) — PDUFA-cycle context, no actual news yet (the Follow-up here is *editorial color* on why the halt is meaningful):

> StreetAccount notes the PDUFA date is 5-Jun for the breast cancer drug vepdegestrant, their oral PROTAC. Pfizer (PFE) has worldwide co-exclusive development and commercial rights; Arvinas (ARVN) is eligible for milestones and royalties from Pfizer. However, on 17-Sep-2025, the companies announced they would select a third-party commercial partner "to unlock the full value of vepdegestrant and ensure vepdegestrant is available promptly if approved for use by regulatory authorities". On their Q4 earnings call (24-Feb-2026), Arvinas stated: "Our discussions to-date with potential partners have been productive and we're working to have an agreement in place before the June 5th PDUFA date." For the latest updates on this story and all top news, please visit the Healthcare Today's Top News page.

CELC 2026-05-01 16:18 ET (`19de53191b173bf9`) — analyst-confirmed conference late-breaker:

> TD Cowen earlier today confirmed that VIKTORIA-1 mutant type data for gedatolisib will be a late-breaker at ASCO 2026 (May 29 - Jun 2). Wrote analyst Tara Bancroft: "We expect the topline VIKTORIA-1 announcement be released imminently." gedatolisib

**Body-content patterns observed:**
- Body always starts with the issuer's full action (`INSM announced that...`, `StreetAccount notes the PDUFA date...`, `TD Cowen earlier today confirmed...`)
- Direct quotes appear with the speaker attribution inline (`"Our discussions to-date with potential partners have been productive..."`)
- Numerical results are reported precisely (`45.5% and 40.3% reduction... compared to a 57.1% reduction in the placebo arm`)
- Status indicators close the body (`INSM remains halted, pending dissemination` → flag for downstream parsers that resume hasn't happened yet)
- Long-form references closer (`For the latest updates on this story and all top news, please visit the Healthcare Today's Top News page.`) — generic boilerplate appended to some Follow-ups but not all

**Token budget:** ~150–500 tokens for body, depending on event type. Cost-relevant for LLM generation in Phase 2.

**Phase 1 scope note.** Follow-up alerts are explicitly **out of Phase 1** (kickoff §"Out of scope"). Phase 1 emits halt + resume only. Phase 2 handles Follow-up generation by ingesting the PR wire / 8-K and producing equivalent fact-dense bodies via LLM, with the templates above as ground truth.

---

## 8. Halt subtype 6 — CORRECTION halt ✅ LOCKED

**Subject:**

```
SA: {TICKER} [CORRECTION: {Company} shares have not been halted]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} CORRECTION: {Company} shares have not been halted (${last_price})
Our prior comment incorrectly indicated shares were halted due to a transposed ticker. The correct company halted is {correct_company} ({correct_ticker}). We have removed our incorrect comment to avoid further confusion.
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (RGEN 2025-11-19 16:11 ET — `19a9df5f2135b214`):**

```
16:11 ET 11/19/25 [StreetAccount] RGEN CORRECTION: Repligen Corp. shares have not been halted ($155.08)
Our prior comment incorrectly indicated shares were halted due to a transposed ticker. The correct company halted is Regeneron (REGN). We have removed our incorrect comment to avoid further confusion.
StreetAccount alert for portfolio(s): · JP Medtech/Biopharma (RGEN)
Tickers mentioned in/related to this story; follow link for 100-day news history: RGEN
```

**sa-monitor implication.** sa-monitor doesn't generate CORRECTION events — it emits halts only when the exchange feed says halt. If a CORRECTION ever fires from SA on a ticker we already alerted on, surface it back to the user as a `:warning:` follow-up message in `#street-account` referencing the original halt's halt-ID. (Edge case for Phase 2.)

---

## 9. Halt subtype 7 — Foreign / ADR halts ✅ LOCKED

**Subject patterns:**
- `SA: {TICKER} [{Company} ADRs halted, news pending]` (US-listed ADR — NVO 2/3/26)
- `SA: {LOCAL_TICKER} [Trading in {Company} shares is halted; ...]` (Euronext / European local — PHIA.NA per v2.1)
- `SA: {LOCAL_TICKER} [{Company} trading lower on phase 3 readout]` (Copenhagen / Nordic — GMAB.DC per v2.1; phrased as "trading lower" not "halted")

**Locked body skeleton (NVO ADR pattern):**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} ADRs halted, news pending (${last_price}{ ±change})
*****Related comments from the archive: {Full text of relevant local-listing comment, often the earnings preview or prior-day primer for the issuer} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER list})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

**Real capture (NVO 2026-02-03 11:36 ET — `19c245d2c55181ee`):**

```
11:36 ET 2/03/26 [StreetAccount] NVO Novo Nordisk ADRs halted, news pending ($57.84 -$1.09)
*****Related comments from the archive: 03-Feb-26 06:10 ET NOVO.B.DC StreetAccount Consensus Metrics Preview - Novo Nordisk Q4 Earnings (DKK 372.55 -DKK 0.50) [...full ~600-token earnings preview body...] * * * * *
StreetAccount alert for portfolio(s): · JP Medtech/Biopharma (NVO)
Tickers mentioned in/related to this story; follow link for 100-day news history: NVO
```

**Notice:** the archive cross-ref here pulls the LOCAL ticker's prior comment (`NOVO.B.DC` Consensus Metrics Preview), showing SA tracks the halt across local + ADR listings. The local-listing earnings preview is a long structured body that's outside the halt-template scope but worth knowing about for the Phase 3 earnings cycle generators.

**sa-monitor coverage interaction.**
- Both NYSE LULD and Nasdaq feeds report ADR halts on US tickers — sa-monitor catches NVO ADR halts directly.
- European-listed halts (PHIA.NA, GMAB.DC) are NOT in those feeds. Foreign-listing halts are out of Phase 1 scope; if you want them later, integration with Euronext / Deutsche Börse / Nasdaq Copenhagen halt feeds is needed.
- The Coverage Manager universe includes some foreign tickers (`4519`, `NOVO.B.DC`, `GMAB.DC`, `PHIA.NA`, `ROG.SW`). The Phase 1 lenient filter passes these through, but the US halt feeds won't fire on them. That's fine — they stay in the universe so we can light up European feeds later without re-importing.

---

---

## 10. Earnings Cycle Wave 2 — Initial EPS/Sales Print ✅ LOCKED

The first earnings-cycle alert that fires after a company reports. Subject and body convey the headline beat/miss vs FactSet consensus and the structured GAAP/non-GAAP financials. Lead time T+0:01 (first SA alert post-print).

**Subject pattern:**

```
SA: {TICKER} [{Company} reports Q? EPS ${X.XX}{ ex-items} vs FactSet ${Y.YY} [{N} est, ${L}-{H}]]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} reports Q? EPS ${X.XX}{ ex-items} vs FactSet ${Y.YY} [{N} est, ${L}-{H}] (${last_price}{ ±change})
Reports Q?: {ad-hoc context sentences if any — e.g. one-time items affecting EPS}
Revenue ${X}B vs FactSet ${Y}B [{N} est, ${L}-{H}B]
{additional line items as relevant: R&D expense, Cash, segment breakdowns}
{FY Guidance ({MMM YYYY}):
EPS ${X}-${Y} vs prior guidance ${A}-${B} and FactSet ${C} [{N} est, ${L}-{H}]
Revenue ${X}-${Y}B vs prior guidance ${A}-${B}B and FactSet ${C}B [{N} est, ${L}-{H}B]
{any other reaffirmed/raised metric guidance — organic growth %, segment growth %, OM %, etc.}}
Reference Link: Press release
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (IDXX 2026-05-05 06:37 ET — `19df7b71f721adf1`):**

```
06:37 ET 5/05/26 [StreetAccount] IDXX IDEXX Laboratories reports Q1 EPS $3.47 vs FactSet $3.41 [13 est, $3.35-3.48] ($563.12)
Reports Q1: Q1 EPS included a $0.05 per share impact from a loss on an equity investment, $0.09 per share in tax benefits from share-based compensation, and $0.14 per share benefit from currency changes.
Revenue $1.14B vs FactSet $1.12B [12 est, $1.10-1.13B]
FY Guidance (Dec 2026):
EPS $14.45 - $14.90 vs prior guidance $14.29-$14.80 and FactSet $14.54 [13 est, $14.37-14.71]
Revenue $4.675-$4.760B vs prior guidance $4.632B-$4.72B and FactSet $4.68B [14 est, $4.65-4.71B]
Organic revenue growth 7.7% - 9.7% vs prior 7.0-9.0%
CAG Diagnostics Recurring Revenue Growth 9.6%-11.6% vs prior 8.6%-10.6%
Reference Link: Press release
StreetAccount alert for portfolio(s): · JP HC Svcs (IDXX)
Tickers mentioned in/related to this story; follow link for 100-day news history: IDXX
```

**Key formatting rules:**
- "vs FactSet ${Y.YY} [{N} est, ${L}-{H}]" — count of estimates and the low-high range. Brackets (not parens), no "$" inside the range.
- "ex-items" appears inline when the EPS is non-GAAP-adjusted (e.g., "EPS $4.47 ex-items vs FactSet $4.24" from VRTX). Absent for GAAP-only reporters.
- Guidance breakdown always contains:
  1. Headline metric vs prior guidance (showing raise/hold/cut)
  2. vs FactSet consensus  
  3. Estimate count + range
- Multi-line guidance (EPS, revenue, organic growth, segment growth) — each gets its own line with the same `vs prior` and `vs FactSet` comparator.

**Token budget:** ~250–600 tokens. Critical Phase 3 cost driver (one of these fires per company per quarter, peak ~80–120/day during 4-6 weeks/quarter).

---

## 11. Earnings Cycle Wave 3 — Metrics Recap ✅ LOCKED

Fires T+5–15 minutes after Wave 2. Drills into segment-level KPIs that the headline EPS/revenue line doesn't cover.

**Subject pattern:**

```
SA: {TICKER} [StreetAccount Metrics Recap - {Company} Q? Earnings]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} StreetAccount Metrics Recap - {Company} Q? Earnings (${last_price})
Key operating metrics:
{Metric category 1, e.g. "Revenue"}
{Segment} ${X} vs FactSet ${Y}{, ±X.X% y/y}
{Segment} ${X} vs FS ${Y}
…
{Metric category 2, e.g. "Organic growth"}
{Segment} ±X.X%
…
{Metric category 3, e.g. "Gross margin"}
{Total} {XX.X%} vs FS {YY.Y%} and year-ago {ZZ.Z%}
{Segment} {XX.X%} ±{Y}bps y/y
…
{Metric category 4, e.g. "Operating margin"} (same shape)
*****Related comments from the archive: {Wave 2 EPS print body inlined} * * * * * {prior Consensus Metrics Preview body inlined if available} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (IDXX 2026-05-05 06:37 ET — `19df7b7808610786`) — body excerpt:**

```
Key operating metrics:
Revenue
Companion Animal Group $1.05B vs FactSet $1.03B
Water $50.3M vs FS $49.1M
LPD $32.5M vs FS $30.1M
Other $4.0M vs FS $4.9M
Organic growth +11%
Companion Animal Group +11.6%
Water +7%
LPD +7%
Gross margin 63.4% vs FS 62.5% and year-ago 62.4%
Companion Animal Group 63.3% +80bps y/y
Water 72.7% +190bps y/y
LPD 52.1% +190bps y/y
Operating margin 31.8% vs FS 31.8% and year-ago 30.9%
Companion Animal Group 32.0% (10bps) y/y
Water 47.1% +120bps y/y
LPD 4.0% +360bps y/y
```

**Formatting variants observed:**
- Either `vs FactSet ${X}` or `vs FS ${X}` — abbreviated form is common in dense metric tables
- Margin format: `{margin} +{bps}bps y/y` for increase, `({bps}bps) y/y` for decrease
- Negative growth: `(7.1%)` (parens, no minus sign)

**Token budget:** ~150–400 tokens for the metrics body, plus the inlined Wave 2 archive cross-ref (which roughly doubles total).

---

## 12. Earnings Cycle Wave 4 — Transcript Intelligence (TI_EARN) ✅ LOCKED

Fires T+1–2 hours after the earnings call ends. GenAI-summarized Q&A, themes, and guidance. **The longest body in the earnings cycle**, ~600–1200 tokens.

**Subject pattern:**

```
SA: {TICKER} [Transcript Intelligence: {Company} Q? Earnings]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} Transcript Intelligence: {Company} Q? Earnings (${last_price}{ ±change})
Call Time: {DD-MMM-YY} {HH:MM} ET
Q&A Summary:
{Bullet 1: 1–3 sentence Q&A summary}
{Bullet 2: …}
… (typically 6–10 bullets)
Themes Summary:
Themes:
{Theme 1}: {1-sentence elaboration}
{Theme 2}: …
Risks:
{Risk 1}: {elaboration}
…
Opportunities:
{Opportunity 1}: …
…
Strategic Adjustments:
{Adjustment 1}: …
…
Guidance Summary:
Nearer-term:
{Forward metric 1, e.g. "Reported revenue $X-$Y in full-year 2026."}
{Forward metric 2}: …
Longer-term:
{Long-term theme 1}: …
{Long-term theme 2}: …
This summary was created with GenAI, optimized by StreetAccount.
Reference Link: Transcript
*****Related comments from the archive: {Wave 3 Metrics Recap body inlined} * * * * * {Wave 2 EPS print body inlined} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (IDXX 2026-05-05 09:49 ET — `19df8684052c9ece`) — body excerpt:**

> Call Time: 05-May-26 08:30 ET
>
> Q&A Summary:
> Confidence remains high in achieving 5,500 inVue placements for the year, despite typical quarterly variability from customer mix.
> Industry outlook for clinical visits has modestly improved; full-year decline now guided to -1.5%, with aging pet population supporting demand.
> [...continues for 7 bullets total...]
>
> Themes Summary: Themes: Expand Diagnostics Utilization: Drive growth through increased diagnostic frequency... Innovation Pipeline Momentum: Accelerate adoption of new platforms (inVue Dx, Cancer Dx, FNA)...
>
> Risks: Consumer Discretionary Pressure: Ongoing macroeconomic headwinds may further reduce wellness visits...
>
> Opportunities: Aging Pet Demographics: Growing older pet population...
>
> Strategic Adjustments: Paced Innovation Rollouts: Broaden controlled launches (e.g., FNA)...
>
> Guidance Summary:
> Nearer-term: inVue Dx instrument placements 5,500 in full-year 2026. Reported revenue $4.675B - $4.760B in full-year 2026. Organic revenue growth 7.7% - 9.7% in full-year 2026. CAG Diagnostics recurring revenue organic growth 8.7% - 10.7% in full-year 2026. EPS $14.45 - $14.90 in full-year 2026. [...]
>
> Longer-term: Multidecade opportunity for diagnostics innovation and utilization driven by the human-animal bond. Continued double-digit international growth supported by commercial expansion and tailored product development. Advancements in AI will accelerate innovation, expand testing access, and deepen patient insights. [...]
>
> This summary was created with GenAI, optimized by StreetAccount.
> Reference Link: Transcript

**Critical structural notes:**
- Section labels (`Q&A Summary:`, `Themes Summary:`, `Guidance Summary:`) are literal headers
- Within Themes Summary the four sub-categories (`Themes:`, `Risks:`, `Opportunities:`, `Strategic Adjustments:`) are always in that order; absence of any one means SA's GenAI didn't surface that flavor
- Each Theme/Risk/etc. is `{Title}: {Sentence}` where Title is Title-Cased and Sentence ends with a period
- Guidance is split Nearer-term / Longer-term as labeled subsections
- The disclaimer line `This summary was created with GenAI, optimized by StreetAccount.` is verbatim and always appears at the end of the GenAI-written body, before the Reference Link

**TI_EARN vs TI_EVENT.** Same template body shape used for non-earnings calls (analyst days, R&D days, trial readout calls). The subject changes from `Transcript Intelligence: {Company} Q? Earnings` to `Transcript Intelligence: {Company} Financial Analyst Day` / `Transcript Intelligence: {Company} Investor Day`. Body grammar identical. See §14 for TI_EVENT details.

**Token budget:** ~600–1200 tokens for Q&A + Themes + Guidance, plus inlined Waves 2 and 3 (~400–800 more tokens). Total per TI_EARN message: ~1000–2000 tokens. **Heaviest cost driver in the earnings cycle.**

---

## 13. Earnings Cycle Wave 5 — Street Takeaways ✅ LOCKED

Fires T+2–24 hours, sometimes next-day. Editorial reaction note synthesizing share move, sell-side analyst commentary, and consensus revisions. The most "newsletter-like" of the earnings waves.

**Subject pattern:**

```
SA: {TICKER} [Street Takeaways - {Company} Q? Earnings]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} Street Takeaways - {Company} Q? Earnings (${last_price}{ ±change})
Overview:
{4-8 sentence narrative summary: share move, key drivers (revenue, EPS, segment performance), guide reaction, sell-side tone}
Analyst Commentary:
{Firm} analyst {Name}{ - raises target / - lowers target}
{1–4 bullets summarizing the analyst's view}
Target ${X}{ from ${Y}} - based on {valuation method}; maintains {Outperform/Buy/Hold/Sell/Underperform}
{Firm} analyst {Name}
{bullets}
Target ${X} - based on {valuation method}; maintains {rating}
… (typically 3–6 firms covered)
Sell-side ratings ({total_count}): Buy {X}% Hold {Y}% Sell {Z}%
The average target {increased/decreased} {±X.X%} to ${Y}, implying {X.X%} upside
Valuation:
NTM P/E {X}x vs five-year average {Y}x and high {H}x, low {L}x
EV/EBITDA {X}x vs five-year average {Y}x and high {H}x, low {L}x
{additional multiples as relevant: P/Sales, EV/Sales, PEG, etc.}
Consensus Estimate Revisions:
{Period}: Revenues ({±X.X%}) to ${Y}B, and EPS ({±$Z.ZZ}, {±X.X%}, to ${W.WW})
{Period}: …
*****Related comments from the archive: {TI_EARN body inlined} * * * * * {Metrics Recap body inlined} * * * * * {EPS print body inlined} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio_1} ({TICKER}) · {Portfolio_2} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (VRTX 2026-05-05 15:13 ET — `19df98fa435c098a`) — body excerpts:**

Overview section (4 sentences):

> Shares (1.2%). Revenue +7.8% y/y was in-line. EPS ex-items beat by 5.4%/$0.23. Growth in Alyftrek led the top line as sales were $424.4M vs $53.9M in the prior year quarter. Trikafta/Kaftrio sales were down (7.7%) y/y. Non-GAAP R&D (2.2%) y/y was below consensus. SG&A +29.8% y/y was 7.8%/$31.3M above expectations. FY26 guide reiterated.

Analyst Commentary section (one analyst block):

> Cantor Fitzgerald analyst Carter Gould
> Calls out reasonably good result as Alyftrek while the top line was slightly above guide and EPS saw healthy upside
> Feels predominant item on call was confidence in povetacicept developing from RAINIER
> Believes management countered any belief povetacicept launch could be slow walked highlighting investment and preparedness
> Thinks SION data ahead likely continues to be an overhang for the CF franchise
> Target $590 - based on DCF; maintains
>
> RBC Capital Markets analyst Brian Abrahams - raises target
> [...bullets...]
> Target $543 from $541 - based on DCF; maintains Outperform

Sell-side block:

> Sell-side ratings (34): Buy 76% Hold 21% Sell 3%
> The average target increased +0.1% to $555.81, implying 31.8% upside

Valuation block:

> NTM P/E 20.9x vs five-year average 22.0x and high 71.0x, low 12.0x
> EV/EBITDA 15.1x vs five-year average 15.0x and high 26.0x, low 9.0x

Estimate revisions block:

> Q2: Revenues (0.2%) to $3.22B, and EPS ($0.01), (0.2%), to $4.74.
> FY2027: Revenues (0.4%) to $14.29B, and EPS ($0.28), (1.3%), to $21.72.

**Critical structural notes:**
- Analyst block format: line 1 is `{Firm} analyst {Name}`, optionally `- raises target` or `- lowers target` suffix; lines 2–N are bullet summaries (no `•` marker — just plain wrapped lines); final line is `Target ${X}{ from ${Y}} - based on {method}; maintains {rating}`
- Multiple analyst blocks separated by blank lines (in source); Wave 5 captures show 4–6 firms typical
- Verb tense in analyst bullets: present-tense narration of the analyst's view (`Calls out`, `Feels`, `Believes`, `Thinks`, `Notes`, `Sees`, `Highlights`, `Reiterates`, `Credits`, `Points to`)
- `Target ${X}{ from ${Y}}` — `from` clause appears only when target was changed
- `maintains` is the literal keyword indicating no rating change; alternatives are `upgrades to {new}` and `downgrades to {new}`
- Sell-side ratings line: integer count, no decimal in percentages
- Valuation multiples always include 5-year average + high + low; never just the multiple alone
- Estimate revisions: format is `({±X.X%}), to ${Y}` for revenue and `({±$Z.ZZ}, {±X.X%}), to ${W.WW}` for EPS — note the parens around negative values

**Multi-portfolio observation.** VRTX appears in TWO portfolios in the footer: `JP Medtech/Tools/DX (VRTX) · Biopharma (VRTX)` (separated by ` · `). This is the "JP Medtech/Biopharma" overlap bucket from v2.1 spec, but rendered as two separate portfolio lines, not the merged "JP Medtech/Biopharma" name. **Correction to v2.1 spec §1.1:** the overlap bucket is just a name shown when the SA UI groups the multi-portfolio assignment; in the email footer they're listed separately.

**Newly-observed portfolio name.** IDXX in §10–§12 is in `JP HC Svcs` — a portfolio NOT in the v2.1 spec's list of 5. The full SA portfolio list (per observed alerts) is at minimum: `Biopharma`, `JP HC Svcs`, `JP Medtech/Tools/DX`, `Non-HC`, `JP PA`. The v2.1 spec's "JP Medtech/Biopharma" appears to be derived display, not a real portfolio name. **Action item for sa-monitor:** since we discarded the SA-portfolio mapping in favor of CM's `Sector (JP)` taxonomy, this discrepancy doesn't affect us — but worth noting if we ever need to parse the footer.

**Token budget:** ~700–1500 tokens for body, plus inlined Waves 2/3/4 (~1000–2000 tokens). Total per Wave 5 message: ~1700–3500 tokens. **Heaviest single message in the cycle.**

---

---

## 14. Investor Day Street Takeaways (TI_EVENT family) ✅ LOCKED

Same body grammar as Wave 5 (§13) but fired after a Capital Markets Day, Analyst Day, R&D Day, or Investor Day rather than an earnings call. Subject line replaces `Q? Earnings` with the event name. Body has all the same Wave-5 sections except **`Consensus Estimate Revisions:` is omitted** (no consensus to revise — the event sets new long-term targets, not a quarterly print).

**Subject pattern:**

```
SA: {TICKER} [Street Takeaways - {Company} {Financial Analyst Day | Investor Day | Capital Markets Day | R&D Day}]
```

**Body skeleton:** identical to §13 (Wave 5 Street Takeaways) except remove the `Consensus Estimate Revisions:` block. The `*****Related comments` block typically inlines the targets/framework alert that fired earlier the same day (e.g., "ServiceNow targets FY30 Subscription revenue $30B+").

**Real capture (NOW 2026-05-05 13:52 ET — `19df946011df5b14`) — body excerpts:**

Overview (4 sentences):

> Shares (0.2%) following the Financial Analyst Day where the Co set a new $30B+ base case for FY30 Subscription revenue, with an upside opportunity of $32B+ along with a durable rule of 60+. Additionally the Co sees ServiceNow AI accounting for ~30% of ACV by FY30. Analysts largely upbeat following the event, viewing the 2030 roadmap as aspirational yet achievable. Key growth drivers include 25%+ CAGRs in core segments and a hybrid pricing model where AI Specialists drive 15x higher volume than basic GenAI. Despite mixed market sentiment, many maintain a bullish outlook, supported by projected ~25% FCF CAGR, disciplined SBC reduction, and a favorable Q2 setup as cRPO growth troughs, providing an attractive risk/reward.

Sell-side block:

> Sell-side ratings (49): Buy 90% Hold 8% Sell 2%
> The average target increased +0.5% to $143.59, implying 56.9% upside

Valuation block (notice 5-year-high may be omitted when there's no clean high):

> NTM P/E 20.5x vs five-year average 56.0x and low 18.0x
> EV/EBITDA 13.5x vs five-year average 37.0x and low 13.0x

Related comments inlines a different alert type — the targets/framework summary that fired earlier:

> 05-May-26 05:49 ET NOW ServiceNow targets FY30 Subscription revenue (Base case) $30B+ - 2026 Financial Analyst Day (yesterday) ($91.97) FY27 target (inc recent acquisitions) Non-GAAP Op margin expansion 100bps Non-GAAP FCF Margin expansion 100bps Long-term targets: FY30 Subscription revenue (Base case) $30B+ (up from $15B+ previous base case target) Upside opportunity FY26 $15B+ 20% CAGR through FY30 FY30 $32B+ opportunity Key growth drivers Security & risk, Data & Analytics, CRM >25% CAGR FY30 ServiceNow AI % of ACV ~30% Durable rule of 60+ for FY30 FY29 SBC % of revenue <10% * * * * *

**Newly-observed portfolio name.** NOW is in `Software` — another portfolio not in the v2.1 spec's list of 5. The observed portfolios in this corpus span at least: `Biopharma`, `JP HC Svcs`, `JP Medtech/Tools/DX`, `Software`, `Non-HC`, `JP PA`. (sa-monitor uses CM's `Sector (JP)` taxonomy directly, so this discrepancy doesn't affect halt routing — but worth flagging if Phase 2's Wave-5 generator ever needs to parse SA portfolio assignments.)

**Investor Day pre-event/live/post-event chain.** Per v2.1 spec §4.M, the full Investor Day cycle has 4–5 waves:
1. Pre-event teaser
2. Live coverage (during event)
3. Targets/framework summary (post-event same day)
4. TI_EVENT Transcript Intelligence (T+1–4 hours)
5. Street Takeaways (sometimes T+next-day)

The §14 capture above is wave 5. Phase 2 sa-monitor would generate waves 3 and 4 (targets summary + TI_EVENT) from the slide deck + transcript ingest; wave 5 needs sell-side ingestion.

---

## 15. Phase 2/3 trial readout — primary endpoint missed ✅ LOCKED

Subject and body are essentially the same template regardless of phase (Phase 1, 2, or 3) and outcome direction (met or missed). The `met its primary endpoint` vs `does not meet primary endpoint` substring in the subject signals direction.

**Subject pattern:**

```
SA: {TICKER} [{Company} reports Phase {N} {STUDY_NAME} study of {drug_name} {does not meet primary endpoint | met primary endpoint | met dual primary endpoints}]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} reports Phase {N} {STUDY_NAME} study of {drug} does not meet primary endpoint (${last_price})
{Body: 5–15 sentences, fact-dense, structured as:
 - Trial design + patient population + dosing regimen
 - Primary endpoint definition + result
 - Secondary endpoints + exploratory analyses (often substantial when primary missed)
 - Safety profile + adverse events
 - Path forward (continue / discontinue / pivot)}
Reference Link: Press release
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER}
```

**Real capture (CORT 2026-04-30 16:24 ET — `19de01049086835d`):**

Body excerpt (the trial-design + endpoint reporting structure):

> The company announced two-year overall survival data from the Phase 2 DAZALS study of its proprietary, selective cortisol modulator dazucorilant in patients with amyotrophic lateral sclerosis (ALS) DAZALS is a randomized, double-blind, placebo-controlled Phase 2 study in which 249 patients with ALS were randomized to receive either 150 mg of dazucorilant, 300 mg of dazucorilant or placebo, daily for 24 weeks Patients who completed the treatment period were eligible to enter the study's long-term extension phase, in which all patients received 300 mg of dazucorilant DAZAL's primary endpoint was the difference in function, as measured by the ALS Functional Rating Scale - Revised (ALSFRS-R), between patients who received dazucorilant and those who received placebo. Overall survival was a secondary endpoint. Although DAZALS did not meet its primary endpoint, at the end of the 24-week treatment period patients who received 300 mg of dazucorilant daily did exhibit improved overall survival (p-value: 0.02) Exploratory analyses show that this survival benefit has continued. In the two years following the start of treatment, patients who received 300 mg of dazucorilant experienced an 87% reduction in the risk of death compared to patients who received placebo and did not switch to 300 mg of dazucorilant in the extension phase (hazard ratio: 0.13; p-value: < 0.0001) [...]

**Critical structural notes:**
- Body is fact-dense narrative prose, no bullets. SA's editorial style: chain sentences without periods between some clauses (`(ALS) DAZALS is a randomized...`).
- Statistical detail is preserved verbatim: hazard ratios, p-values with `<` operators, percentage reductions
- Path-forward signal at the end (`Corcept is conducting a dose titration study to refine methods of improving dazucorilant's gastrointestinal tolerability and inform the program's path forward`)
- No `*****Related comments` block when the news is the original announcement (i.e., no prior catalyst-day call alert to cross-ref)

**Phase 3 met variant** is structurally identical with `met its primary endpoint` in subject + body. Same trial design + endpoint reporting + safety + path-forward sequence. Common headlines: `[CYTK reports ACACIA-HCM Phase 3 met dual primary endpoints]`, `[VRDN reports Phase 3 REVEAL-2 trial of elegrobart in chronic thyroid eye disease met its primary endpoint]`.

**CORRECTION variant for trial readouts** observed (CORT 2026-04-30 16:46 — `19de0255a42f76eb`): SA issues `CORRECTION: Corcept previously reported phase 2 DAZALS study of dazucorilant in ALS missed its primary endpoint, in 2024; today's announcement was 2-year OS data` when the original alert mischaracterized the readout. Same CORRECTION body shape as §8.

**Token budget:** ~400–800 tokens depending on trial complexity. Mid-cost driver in Phase 2.

---

## 16. FDA approval ✅ LOCKED

Subject pattern varies — multiple framings observed depending on whether the alert is the FDA's own announcement, the issuer's press release, or a follow-up:

```
SA: {TICKER}{[. Also: {SECONDARY}]} [FDA approves {DRUG_BRAND} for {indication}]
SA: {TICKER}{[. Also: {SECONDARY}]} [{Issuer} issues press release on FDA approval of {DRUG_BRAND} for the treatment of {indication}]
SA: {TICKER}{[. Also: {SECONDARY}]} [Follow-up: FDA approves {DRUG_BRAND} for {indication}]
```

The cycle for a typical halted-and-approved name produces 3 SA alerts in sequence (10–30 minutes apart):

1. **Initial halt** (subtype 1 from §3) — `[{Company} halted, news pending]`
2. **Headline approval** — `[FDA approves {DRUG_BRAND} for {indication}]` — usually short body
3. **Follow-up: FDA approves** — full body with FDA's exact indication language + companion-diagnostic mention + warnings + PDUFA-relative timing
4. **Issuer press release** — `[{Issuer} issues press release on FDA approval...]` — issuer's perspective + partnership context

**Locked body skeleton (Issuer press release variant — the most substantive):**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Issuer} issues press release on FDA approval of {DRUG_BRAND} ({drug_generic_name}) for the treatment of {full indication string} (${last_price}{ ±change})
{Issuer} today{ with its partner {Partner} ({PARTNER_TICKER}),} announced that the FDA has granted approval for {DRUG_BRAND} ({drug_generic_name}) for the treatment of {full FDA-approved indication, often verbatim from FDA label}.
{Optional: Approval received in advance of FDA-assigned PDUFA date of {date};}
{Optional: 1–3 sentences on partnership / commercial-rights / sales-channel}
Reference Link: Press release
*****Related comments from the archive: {Inlined Follow-up FDA approves comment with FDA wording} * * * * * {Inlined original halt notice} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio_1} ({TICKER list_1}) · {Portfolio_2} ({TICKER list_2})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

**Real capture (ARVN 2026-05-01 12:48 ET — `19de47146cc63afa`):**

```
12:48 ET 5/01/26 [StreetAccount] ARVN Arvinas issues press release on FDA approval of VEPPANU (vepdegestrant) for the treatment of ESR1M, ER+/HER2- advanced breast cancer ($10.27 +$0.37)
Arvinas today with its partner Pfizer Inc. (PFE), announced that the FDA has granted approval for VEPPANU (vepdegestrant) for the treatment of adults with estrogen receptor-positive (ER+)/human epidermal growth factor receptor 2-negative (HER2-), estrogen receptor 1 (ESR1)-mutated advanced or metastatic breast cancer, as detected by an FDA-authorized test, with disease progression following at least one line of endocrine therapy.
Approval received in advance of FDA-assigned PDUFA date of 5-Jun-26; Arvinas and Pfizer remain on track to announce selection of a third party.
Reference Link: Press release
*****Related comments from the archive: 01-May-26 12:31 ET ARVN Follow-up: FDA approves Veppanu for ESR1M, ER+/HER2- advanced breast cancer ($10.27 +$0.37) FDA approved Veppanu (vepdegestrant , a heterobifunctional protein degrader, for adults with estrogen receptor (ER)-positive, human epidermal growth factor receptor 2 (HER2)-negative, ESR1-mutated advanced or metastatic breast cancer, as detected by an FDA-authorized test, with disease progression following at least one line of endocrine therapy. FDA also approved the Guardant360 CDx as a companion diagnostic device to identify patients with breast cancer with ESR1 mutations for treatment with vepdegestrant. The prescribing information includes warnings and precautions for QTc interval prolongation and embryo-fetal toxicity. The FDA approved this application one month ahead of the FDA goal date. Shares of ARVN remain halted. * * * * * 01-May-26 12:28 ET ARVN FDA approves Veppanu for ESR1M, ER+/HER2- advanced breast cancer ($10.27 +$0.37) * * * * *
StreetAccount alert for portfolio(s): · JP Medtech/Tools/DX (PFE) · Biopharma (ARVN, PFE)
Tickers mentioned in/related to this story; follow link for 100-day news history: ARVN, PFE
```

**Critical structural notes:**
- The full FDA-approved indication is reproduced verbatim (or nearly so) — observe the exact `(ER+)/human epidermal growth factor receptor 2-negative (HER2-)` punctuation
- Companion-diagnostic device approvals usually appear in the cross-referenced Follow-up alert
- PDUFA-relative timing (`Approval received in advance of FDA-assigned PDUFA date of {date}`) is a flagged moment for reading whether SA expected this
- Multi-portfolio footer is the norm because partners often appear (`PFE` shows up in both `JP Medtech/Tools/DX` and `Biopharma`)

**Token budget:** ~250–500 tokens for the issuer-press-release variant. Cross-refs typically push total to 600–1000 tokens.

---

## 17. GLP-1 Rx Tracker (^GLP1 weekly) ✅ LOCKED

Weekly Friday digest of IQVIA prescription data for the GLP-1 / incretin class. Mirrors Wave-5 Street Takeaways grammar but for a weekly data product, not a stock-specific event. **Highest-overlap to Jason's existing GLP-1 monitor work** — the data-table portion is the core of what sa-monitor's Phase 4 GLP-1 Tracker would produce.

**Subject pattern:**

```
SA: ^GLP1, LLY, NVO [Street Takeaways - GLP-1 Rx Tracker for week ended {Month-Day}; {key data point}; {key data point}]
```

The subject embeds 1–2 of the most newsworthy delta data points (e.g., `Foundayo Week 3 TRx 5.61K vs 3.71K w/w; Oral Wegovy TRx rises ~8.1% w/w`).

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] Street Takeaways - GLP-1 Rx Tracker for week ended {date}; {key delta 1}; {key delta 2}
GLP1 Rx Weekly data recap (IQVIA Data)
Overview:
{2–4 sentence narrative summary of the week's key dynamics}
Obesity GLP-1
{Drug 1 (Zepbound)} TRx ±{X.X}%, while NBRx ±{X.X}% with TRx share at {YY.Y}% vs {ZZ.Z}% prior, while {Drug 2 (Wegovy)} TRx/NBRx rose ±{X.X}%/±{X.X}% w/w with TRx share at {YY.Y}% up from {ZZ.Z}% prior
Diabetes GLP-1
{Drug 1 (Ozempic)} TRx/NBRx rose ±{X.X}%/±{X.X}%, with TRx share at {YY.Y}%, {Drug 2 (Mounjaro)} TRx/NBRx gained ±{X.X}%/±{X.X}% w/w, with TRx share at ~{YY.Y}%, while {Drug 3 (Trulicity)} TRx was rose ±{X.X}% but NBRx fell ±{X.X}% with an ±{X.X}% TRx share.
Analyst Commentary:
{Firm} analyst {Name}{ ({TICKER subject})}
{1–5 bullet summaries of the analyst's view}
{Firm} analyst {Name}
{bullets}
… (typically 4–6 firms)
StreetAccount alert for portfolio(s): · {Portfolio_1} ({TICKER list}) · {Portfolio_2} ({TICKER list})
Tickers mentioned in/related to this story; follow link for 100-day news history: ^GLP1, {TICKER list}
```

**Real capture (2026-05-01 11:14 ET — `19de41b8f5636c51`) — body excerpts:**

Overview:

> Overall U.S. incretin prescriptions fell slightly w/w, while new scripts were 1.7% higher, driven primarily by Wegovy strength, offsetting declines in Zepbound. In week three, Foundayo TRx reached 5,612, up from 3,707 w/w, though comments on the LLY's recent earnings call point to ~20K TRx at 3 and 1/2 weeks, suggests current data likely suffers from a capture rate issue. Oral Wegovy TRx reached ~134.8K (IQVIA) rising ~8.1% w/w. It was noted that IQVIA data doesn't fully capture NovoCare and telehealth provider scripts.

Obesity / Diabetes data lines:

> Obesity GLP-1 Zepbound TRx fell 5.7%, while NBRx rose 0.1% with TRx share at 57.4% vs 59.6% prior, while Wegovy TRx/NBRx rose 3.3%/5.7% w/w with TRx share at 42.6% up from 40.3% prior
> Diabetes GLP-1 Ozempic TRx/NBRx rose 0.5%/0.6%, with TRx share at 35.6%, Mounjaro TRx/NBRx gained 1.2%/0.9% w/w, with TRx share at ~52.4%, while Trulicity TRx was rose 0.2% but NBRx fell 0.3% with an 8.6% TRx share.

Analyst Commentary block (one example):

> RBC Capital Markets analyst Trung Huynh (LLY)
> Sees week 3 Foundayo TRx of 5.6K likely to be received negatively
> Points to yesterday's earnings call indicating ~20K patients are on Foundayo after 3.5 weeks, which suggests current data likely suffers from a capture rate issue
> Notes LLY confirming the retail sample is small and the telehealth channel still has significant data gaps
> Sees by weeks 8-12, launch trajectories typically stabilize as growth rates, with refill patterns, and prescriber breadth becoming more predictable
> Points out meeting ~$1.4B consensus, would mean Foundayo reaching 90k+ weekly TRx by mid-June and average ~150k weekly for the full year

**Differences from Wave-5 Street Takeaways:**
- **No** `Sell-side ratings (...)` block — there's no single ticker to rate
- **No** `Valuation:` block — same reason
- **No** `Consensus Estimate Revisions:` block — same reason
- Analyst Commentary blocks lack the `Target ${X} - based on {method}; maintains {rating}` close — the analysts here are commenting on a sector data print, not a stock event
- The analyst's primary ticker (e.g., `(LLY)`) is appended to the analyst-name line in parentheses to indicate which name they're commenting on
- Multi-portfolio footer always (LLY + NVO appear in two portfolios in the observed corpus)

**Token budget:** ~600–1000 tokens for body. Recurring weekly cost driver if Phase 4 generates this from raw IQVIA data.

**sa-monitor implication.** Per kickoff §5 and v2.1 §6.2, this is the highest-overlap pre-existing work. If you can get IQVIA Xponent (or NPA Audit) data, Phase 4 sa-monitor publishes the Rx tracker with deeper coverage cuts than SA's generic version. IQVIA is institutional-priced; Symphony Health and GoodRx claims data are cheaper alternatives.

---

## 18. Notable Drug Events (^BIOEVENTS weekly) ✅ LOCKED

Sunday/Monday weekly digest of upcoming clinical and regulatory catalysts for the coverage universe. Calendar-style organization, no analyst commentary.

**Subject pattern:**

```
SA: ^BIOEVENTS, ^HEALTH, {TICKER1}, {TICKER2}, others [StreetAccount Summary: Notable Drug Events expected for the week of {Month-Day}{ (cont.)}]
```

The `(cont.)` suffix indicates this is part 2 of a multi-part digest (typically the second half of the week + later-month items).

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] StreetAccount Summary: Notable Drug Events expected for the week of {Month-Day} (cont.)
Industry meeting with clinical data:
{Conference name} {YYYY} ({date range}) ({TICKER1}, {TICKER2}, {TICKER3})
{Day-of-week} {DD-MMM}
{Event category}:
{TICKER}: {Event description} ({HH:MM}ET)
…
{Day-of-week} {DD-MMM}
…
later during {Month YYYY}
Regulatory decisions:
FDA PDUFAs: {TICKER} ({drug} {filing_type}, {DD-Mon}), …
EMA CHMP opinions on {filing}: ({DD-Mon})
Regulatory meeting:
EMA CHMP monthly meeting ({Month DD-DD})
Industry meetings with clinical data:
{Conference name} ({date range}); …
Trial results:
{TICKER} (Ph{N} {indication}), …
StreetAccount alert for portfolio(s): · {Portfolio_1} ({TICKER list_1}) · {Portfolio_2} ({TICKER list_2})
```

(Note: this digest does NOT have a `Tickers mentioned in/related to this story; follow link...` line — likely because there are too many tickers to list.)

**Real capture (2026-05-01 14:34 ET — `19de4d2b415791b9`) — body excerpt:**

> StreetAccount Summary: Notable Drug Events expected for the week of 3-May (cont.)
> Industry meeting with clinical data:
> Digestive Disease Week (DDW) 2026 (May 2-5) (XNCR, JNJ, ERPX)
> Sun 3-May
> Industry meeting with clinical data
> Association for Research in Vision and Ophthalmology (ARVO) 2026 (May 3-7) (IRD, SRZN, OKYO)
> Mon 4-May
> Investor meeting: CATX Investor Day (8:30ET)
> Tue 5-May
> Investor meeting: CLYM R&D Day (8:00ET)
> Fri 8-May
> Abstracts release: ASGCT late-breaking abstracts released (16:30ET)
> later during May 2026
> Regulatory decisions:
> FDA PDUFAs: ARGX (Vyvgart sBLA, 10-May), 4523.JP (Leqembi IQLIK sBLA, 24-May), MNKD (Afreeza sBLA, 29-May), CING (dexmethylphenidate NDA, 31-May); EMA CHMP opinions on MAA (22-May)
> Regulatory meeting: EMA CHMP monthly meeting (May 18-21)
> Industry meetings with clinical data: American Society of Gene & Cell Therapy (ASGCT) Meeting (May 11-15); American Thoracic Society (ATS) International Conference (May 15-20); International Society for the Study of Vascular Anomalies (ISSVA) World Congress (May 19-22); EASL Congress (May 27-30); American Society of Clinical Oncology (ASCO) Meeting (May 29-Jun 2)
> Trial results: PTGX (Ph3 PsA), RLAY (Ph2 vascular anomalies), WVE (Ph1 AATD)

**Critical structural notes:**
- No price line, no related-comments cross-ref
- Conference names are spelled out with abbreviation in parens: `Digestive Disease Week (DDW) 2026`
- PDUFA entries are tightly formatted: `{TICKER} ({drug_name} {filing_type}, {DD-Mon})`
- Trial-results entries: `{TICKER} (Ph{N} {indication})`
- Multi-portfolio footer can have many tickers per portfolio

**Token budget:** ~400–700 tokens. Weekly cost driver for Phase 4.

**sa-monitor Phase 4 implication.** This digest is the source-of-truth catalyst calendar. Phase 4 sa-monitor would produce the `#sa-weekend-digest` channel content from a combination of: ClinicalTrials.gov NCT registry, FDA PDUFA calendar, EMA CHMP schedule, and conference embargo dates. The output would be a slimmed sa-monitor version filtered to your coverage universe (Healthcare Services + MedTech + non-HC; biotech excluded per Phase 1 filter, though Phase 4 may revisit).

---

---

## 19. Phase 2/3 trial readout — primary endpoint MET ✅ LOCKED

Same body grammar as the trial-miss template in §15 but with a richer per-arm efficacy table when the readout is positive. Body extends to 800–1500 tokens because successful readouts get the full structured efficacy data dump.

**Subject pattern:**

```
SA: {TICKER}{[. Also: {SECONDARY}]} [{Company} reports Phase {N} {STUDY_NAME} {trial of drug in indication} met its primary endpoint]
```

Common subject variants:
- `met its primary endpoint`
- `met dual primary endpoints` (when the trial has co-primary endpoints, e.g., FDA + EMA endpoints)
- `achieves primary endpoint in {sub-population}` (when met in a specific patient subset)

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] {TICKER} {Company} reports Phase {N} {STUDY_NAME} trial of {drug} in {indication} met its primary endpoint (${last_price})
{Company} announced topline data from the {STUDY} phase {N} clinical trial of {drug} in patients with {full disease descriptor}.
{STUDY} met its primary endpoint{ for both the {regulatory_body_1} and {regulatory_body_2}} with high statistical significance (p < {value}).
{Optional: secondary-endpoint summary sentence}
{Efficacy table:}
Results from primary and all key secondary endpoints at week {N}:
{Drug arm 1} (n={N}):
{Endpoint family 1}:
{Specific endpoint description} ({primary_endpoint_label}): {value}{%} (p {operator} {value})
…
{Endpoint family 2}: …
{Drug arm 2} (n={N}):
…
Placebo (n={N}):
…
{Safety paragraph: 2–4 sentences on tolerability, adverse events, common AE rates}
{Optional: completion-rate sentence}
{Path-forward sentence: BLA submission timing, advancement plan}
{Optional: conference-call dial-in if a same-day call is scheduled}
{TICKER} shares remain halted
Reference Link: Press release
*****Related comments from the archive: {Inlined original halt notice} * * * * *
StreetAccount alert for portfolio(s): · {Portfolio} ({TICKER list, often plus partner})
Tickers mentioned in/related to this story; follow link for 100-day news history: {TICKER list}
```

**Real capture (VRDN 2026-05-05 07:05 ET — `19df7d0ffed4ea36`) — body excerpts:**

Trial-overview opening (the standard 1–2 sentence frame):

> Viridian Therapeutics announced topline data from the REVEAL‑2 phase 3 clinical trial of elegrobart in patients with chronic thyroid eye disease (TED). REVEAL-2 met its primary endpoint for both the FDA and European Medicines Agency (EMA) with high statistical significance (p < 0.0001). In addition, REVEAL-2 met all its proptosis key secondary endpoints in the Q4W and Q8W treatment arms with high statistical significance, and the Q4W treatment arm showed a statistically significant diplopia responder rate at week 24.

Efficacy table (per-arm structure, abbreviated):

> Results from primary and all key secondary endpoints at week 24:
> Elegrobart Q4W (n=70):
> Proptosis:
> Proptosis responder rate (exophthalmometry) (FDA Primary Endpoint): 50% (p < 0.0001)
> Overall responder rate (ORR)¹ (EMA Primary Endpoint): 47% (p < 0.0001)
> Proptosis mean change from baseline (exophthalmometry): -1.9 mm (p < 0.0001)
> Diplopia:
> Diplopia responder rate: 61% (p = 0.0118)
> Diplopia complete resolution: 44% (p = 0.0295)
> Elegrobart Q8W (n=68):
> [...same shape...]
> Placebo (n=66):
> [...placebo arm always last; no p-values since these are reference]

Safety + path-forward:

> Elegrobart was generally well tolerated in REVEAL‑2 with a safety profile consisting of adverse events generally expected from the anti-IGF-1R class, the vast majority of which were mild. Rates of hearing impairment were low in both the Q4W and Q8W treatment arms (4.1% and 8.8% placebo-adjusted rates, respectively). 91% of elegrobart-treated patients completed the full course of treatment, and there were no treatment-related serious adverse events (SAEs). Viridian remains on track to submit a Biologics License Application (BLA) to the U.S. FDA for elegrobart in Q1 2027. Viridian will host a conference call today at 8:00 a.m. ET to discuss the REVEAL‑2 topline data. Dial‑in (U.S.): (800) 715-9871 Dial‑in (International): +1 (646) 307-1963 Conference ID: 7373356 VRDN shares remain halted

**Critical structural notes:**
- Per-arm structure is deeply nested: Arm → Endpoint family → Specific endpoint with regulatory label → Result + p-value
- Regulatory labels in parens after endpoint description: `(FDA Primary Endpoint)`, `(EMA Primary Endpoint)`
- Stat formatting: `(p < 0.0001)` for highly significant, `(p = 0.0118)` for borderline-significant — preserve operators verbatim
- Per-arm sample size always shown: `(n=70)`
- Placebo arm always last in the table, no p-values (it's the reference)
- Footnote markers (`¹`) for special endpoint definitions — SA preserves these
- "shares remain halted" indicator — flag for downstream parsers that resume hasn't fired yet
- Conference-call dial-in info appears verbatim including phone numbers + conference ID (a privacy nuance to consider — sa-monitor's regenerated body should keep these but the user might want to scrub if downstream messaging is broader)
- Unicode characters used: non-breaking hyphen `‑` in `REVEAL‑2` and dial-in (`Dial‑in`); copy-paste preserves these

**Token budget:** ~800–1500 tokens for body. Highest single-message cost in the trial-readout family.

---

## 20. Healthcare Pre-Market Sector Summary (^HEALTHPRE) ✅ LOCKED

The longest-form template in the SA corpus. Daily 7:30–9:00 ET digest covering the entire healthcare sector — earnings overnight, regulatory news, pharma/biotech/medtech/services subsectors, on-deck tonight's reports, tomorrow's calendar.

**Subject pattern:**

```
SA: ^HEALTH, ^HEALTHPRE, {TICKER1}, {TICKER2}, {TICKER3}, others [StreetAccount Sector Summary - Healthcare Pre-Market]
```

Subject embeds the first 3 alphabetical tickers covered + `others`. The "others" can hide 30–80 additional tickers in a busy session.

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] StreetAccount Sector Summary - Healthcare Pre-Market
Synopsis
{2–4 paragraphs of narrative summary highlighting: earnings calendar weight, biggest beats/misses, regulatory news, biotech catalysts, sector tone}
Macro
{1–2 paragraphs on broad-market backdrop, geopolitics, key macro drivers}
Pre-market trading update
Trading higher
+{XX.X%} {TICKER} {short reason}
+{XX.X%} {TICKER} {short reason}
…
Trading lower
-{XX.X%} {TICKER} {short reason}
-{XX.X%} {TICKER} {short reason}
…
Pharma
Earnings:
{Multi-paragraph earnings summary, one paragraph per company. Format: "{TICKER} reports Q? EPS ${X} ex-items vs FactSet ${Y} on revenue ${Z}B vs FS ${W}B. {Guidance reaction}. Conf. call at {HH:MM}ET"}
Corporate:
{Bullet items on M&A / leadership / capital actions}
Regulatory:
{Bullet items on FDA / HHS / CMS / EMA actions}
Biotech
Trial results:
{Multi-paragraph trial result summaries — same format as §15/§19}
Earnings:
{...}
Research:
{Sell-side initiations / upgrades / downgrades — format: "{TICKER} initiated {rating} at {Firm} ({analyst}), target is ${X} or approx. {Y}% upside."}
Life Science & MedTech
{Same structure as Pharma/Biotech: Earnings / Corporate / Regulatory / Research}
Services & Hospitals
{Same structure}
On Deck:
Earnings after the close
{TICKER list with call times: "{TICKER} (call at {HH:MM}ET), {TICKER} (call Wed at {HH:MM}ET), …"}
Earnings tomorrow {Day} {DD-Mon}:
before
{TICKER list}
after
{TICKER list}
This summary (along with intraday updates) can also be found on the Healthcare Today's Top News page.
StreetAccount alert for portfolio(s): · {Portfolio_1} ({long ticker list, can be 30+ tickers}) · {Portfolio_2} ({long ticker list}) · {Portfolio_3} ({long ticker list})
```

(Note: this template does NOT include a `Tickers mentioned in/related to this story; follow link for 100-day news history` line — the ticker count is too long.)

**Real capture (2026-05-05 08:57 ET — `19df8371a113d8bd`) — pre-market trading list excerpt:**

> Pre-market trading update
> Trading higher
> +32.0% VRDN trial resuits in TED; earnings
> +23.9% EWTX sympathy to CYTK
> +21.6% CYTK trial results in non-obstructive HCM
> +13.3% ABCL initiation
> +10.0% WAT earnings
> +8.4% RYTM earnings
> +7.2% SHC earnings
> +3.9% IDXX earnings
> [...]
> Trading lower
> -45.0% WGS earnings
> -43.2% EMBC earnings
> -10.6% INSP earnings, guidance, downgrades
> -5.7% IQV earnings
> [...]

Pharma earnings paragraph excerpt:

> PFE reports Q1 EPS $0.75 ex-items vs FactSet $0.72 on revenue $14.45B vs FS $13.84B. COVID products and Xtandi miss, but broad outperformance Eliquis, Prevnar, Ibrance and others more than offset. Reaffirms FY26 guidance top and bottom. Conf. call at 10:00ET

Biotech trial-results entry:

> CYTK announced topline results from phase 3 ACACIA-HCM study of aficamten [Myqorzo] (BAYN.GR) in adults with non-obstructive HCM. Trial met dual primary endpoints of KCCQ and Maximal Exercise Performance with consistent positive findings across key secondary endpoints. (BMY for Camzyos (mavacamten) read-across; EWTX) Conf. call at 8:00ET

Multi-portfolio footer (extreme case — observed three portfolios with 30+ tickers each):

> StreetAccount alert for portfolio(s): · JP HC Svcs (COR, CVS, DVA, ELAN, FMS, FRE.GR, HSIC, IDXX, IQV, NVST, OSCR) · JP Medtech/Tools/DX (ALC, BMY, BRKR, ELAN, EW, HSIC, INSP, ISRG, LIVN, NVO, NVST, PFE, PODD, QGEN, RGEN, RVTY, SHC, SN.LN, SNN, SOLV, TECH, TEM, TMDX, TWST, VRTX, WAT) · Biopharma (ABCL, ACAD, ALKS, BMRN, BMY, BNTX, CYTK, ELAN, EXEL, JAZZ, MDGL, MIRM, NBIX, NVO, OCUL, ONC, PFE, RPRX, RVMD, RVTY, RYTM, SION, TECH, TEM, TVTX, UTHR, VRDN, VRTX, VTRS)

**Critical structural notes:**
- Section headers (`Synopsis`, `Macro`, `Pre-market trading update`, `Pharma`, `Biotech`, `Life Science & MedTech`, `Services & Hospitals`, `On Deck:`) are literal — used as semantic anchors by sa-monitor's parser
- Subsection headers (`Earnings:`, `Corporate:`, `Regulatory:`, `Trial results:`, `Research:`) follow the same pattern within each major section
- Pre-market list ranges from ~10 to ~50 tickers in a single message
- The sign in pre-market list: `+{X}%` for up, `-{X}%` for down (notice plain minus, not parens)
- Within earnings paragraphs, the EPS formatting matches Wave 2 (§10): `Q1 EPS $X ex-items vs FactSet $Y`
- Trial-results entries within HC Pre-Market are abbreviated single-paragraph summaries; the full readout body lives in its own dedicated alert (§19/§15)
- "Quick Take" and "Quick take" subsections appear after some company entries to summarize sell-side reaction

**Token budget:** ~3000–6000 tokens for body. **Heaviest single SA message in the corpus.** Recurring daily during peak earnings season; cost-relevant if Phase 5 generates this from raw inputs.

**sa-monitor Phase 5 implication.** The HC Pre-Market is one of the templates that's most expensive to recreate well — it's effectively SA's editorial daily of the entire healthcare sector. The Phase 5 daily morning brief in the kickoff is a slimmed version (only Tier 3 priority items: macro headlines, 52-week H/L on coverage names, today's notable drug events). Full-fidelity HC Pre-Market matching is out of Phase 1-5 scope per kickoff and probably not worth pursuing — SA's editorial flow is the comparative advantage here, not their data.

---

## 21. Earnings Scorecard (^EARNSCORE weekly) ✅ LOCKED

Weekly Friday-during-earnings-season digest of FactSet's Earnings Insight stats. **Shortest of the weekly digests** — pure data summary, no analyst commentary.

**Subject pattern:**

```
SA: ^EARNSCORE [StreetAccount Scorecard - Earnings: US Equities]
```

**Locked body skeleton:**

```
{HH:MM} ET {M/DD/YY} [StreetAccount] ^EARNSCORE StreetAccount Scorecard - Earnings: US Equities
According to FactSet's latest Earnings Insight report, the blended earnings growth rate for Q? S&P 500 EPS currently stands at {X.X}%. This is above/below the {Y.Y}% expected at the end of the quarter.
The blended revenue growth rate is {X.X}%.
Of the {X}% of S&P 500 companies that have reported for Q?, {X}% have beaten consensus EPS expectations, above/below the {Y}% one-year average and the five-year average of {Z}%.
In addition, {X}% have surpassed consensus sales expectations, above/below the {Y}% one-year average and the five-year average of {Z}%.
In aggregate, companies are reporting earnings that are {X.X}% above expectations, above/below the {Y.Y}% one-year average positive surprise rate and the five-year average of {Z.Z}%.
In aggregate, companies are reporting sales that are {X.X}% above expectations, above/below the {Y.Y}% one-year positive surprise rate and matching the five-year average of {Z.Z}%.
Reference Link
StreetAccount alert for news category: · Content Summaries: Earnings Scorecard
Tickers mentioned in/related to this story; follow link for 100-day news history: ^EARNSCORE
```

**Real capture (2026-05-01 14:45 ET — `19de4dc74bd3f94c`):**

```
14:45 ET 5/01/26 [StreetAccount] ^EARNSCORE StreetAccount Scorecard - Earnings: US Equities
According to FactSet's latest Earnings Insight report, the blended earnings growth rate for Q1 S&P 500 EPS currently stands at 27.1%. This is above the 13.2% expected at the end of the quarter.
The blended revenue growth rate is 11.1%.
Of the 63% of S&P 500 companies that have reported for Q1, 84% have beaten consensus EPS expectations, above the 79% one-year average and the five-year average of 78%.
In addition, 81% have surpassed consensus sales expectations, above the 73% one-year average and the five-year average of 70%.
In aggregate, companies are reporting earnings that are 20.7% above expectations, above the 7.2% one-year average positive surprise rate and the five-year average of 7.3%.
In aggregate, companies are reporting sales that are 1.9% above expectations, above the 1.6% one-year positive surprise rate and matching the five-year average of 2.0%.
Reference Link
StreetAccount alert for news category: · Content Summaries: Earnings Scorecard
Tickers mentioned in/related to this story; follow link for 100-day news history: ^EARNSCORE
```

**Critical structural notes:**
- Footer is **`StreetAccount alert for news category:`** — NOT `for portfolio(s):` — because this is a content-summary alert, not a portfolio-routed alert
- "Reference Link" appears without label suffix (just `Reference Link` not `Reference Link: Press release`)
- All percentages reported with 1 decimal place
- Sentence structure is templatized: same 6 sentences with different numbers each week, easy to LLM-generate from raw FactSet Earnings Insight data

**Token budget:** ~150–200 tokens. Cheapest weekly digest. Phase 4 sa-monitor would generate this trivially from FactSet's Earnings Insight PDF (or scraped equivalent).

---

## A. Status — D3 v1 ✅ COMPLETE

All 19 templates documented. Phase 1 critical halt subtypes (§3–§9) and Phase 2-3 templates (§10–§21) are now fully locked from real Gmail full-body captures.

| Template | Section | Status |
|---|---|---|
| 1. Halt — basic | §3 | ✅ Locked |
| 2. Halt with Note | §4 | ✅ Locked |
| 3. Halt cross-ref to broken news | §5 | ✅ Locked |
| 4. Resume | §6 | ✅ Locked |
| 5. Follow-up to halted news | §7 | ✅ Locked |
| 6. CORRECTION | §8 | ✅ Locked |
| 7. Foreign / ADR halt | §9 | ✅ Locked |
| 8. Earnings Wave 2 (EPS print) | §10 | ✅ Locked |
| 9. Earnings Wave 3 (Metrics Recap) | §11 | ✅ Locked |
| 10. Earnings Wave 4 (TI_EARN) | §12 | ✅ Locked |
| 11. Earnings Wave 5 (Street Takeaways) | §13 | ✅ Locked |
| 12. TI_EVENT (Investor Day Takeaways) | §14 | ✅ Locked |
| 13. Phase 3 met (trial readout) | §19 | ✅ Locked |
| 14. Phase 3 missed (trial readout) | §15 | ✅ Locked |
| 15. FDA approval | §16 | ✅ Locked |
| 16. HC Pre-Market Sector Summary | §20 | ✅ Locked |
| 17. GLP-1 Rx Tracker | §17 | ✅ Locked |
| 18. Notable Drug Events | §18 | ✅ Locked |
| 19. Earnings Scorecard | §21 | ✅ Locked |

**D3 v1 ready for sign-off. D4 unblocked.**

---

## B. Phase 1 D4 unblocking summary

**All Phase 1 halt subtypes are now locked.** D4 (halt feed prototype) can use the §3 (basic halt) and §6 (resume) templates directly. Subtypes 2, 3, 5 are reference for Phase 2; subtype 6 is an edge case to handle defensively in Phase 2; subtype 7 is observed but covered by sa-monitor's halt feed only for US-ADR tickers (not European local listings).

**Status:** Phase 1 halt portion of D3 is ready for sign-off. D4 unblocked.
