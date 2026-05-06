# Phase 1 Data Sources

**Project:** sa-monitor (StreetAccount halt-feed recreation, Phase 1)
**Author:** Claude
**Date:** 2026-05-05
**Status:** **routing locked 2026-05-05.** All §9 questions resolved; sample-captures (§7) still stubbed pending workspace egress allowlist update.

This is Deliverable 1 per `cowork-phase1-kickoff.md`. Covers: data-source endpoints + schemas, reason-code reference, latency/rate-limit characteristics, polling-vs-websocket recommendation, sample captures (stubbed), routing decisions, and the existing-stack inventory that informed those decisions.

---

## 1. Existing-stack inventory (informing infra choices)

This section absorbs the kickoff's separate `existing-stack-inventory.md` since the routing decisions in §3–§6 depend on it directly.

### Confirmed available, will reuse

| Capability | Source | sa-monitor use |
|---|---|---|
| Coverage universe | `Coverage Manager/exports/universe.csv` + `universe_metadata.json` (schema v2, validated, ~1,095 tickers) | Read-only filter for halt-event allow-list. Schema `assert status["schema_version"] == 2` per the Coverage Manager export contract |
| Position state | `Coverage Manager/exports/portfolio.json` + `researching.json` | Optional: tag halts on names you actively own/research |
| Slack delivery | Webhook on the existing "Earnings Agent Bot" Slack app (JP Personal Hub workspace) | Single consolidated channel `#street-account` for ALL sa-monitor alerts across Phases 1–5 (revised 2026-05-05; supersedes kickoff's 5-channel split). Env var: `SLACK_WEBHOOK_STREET_ACCOUNT` |
| Health heartbeat | Shared `SLACK_WEBHOOK_STATUS_REPORTS` per `HEALTH_REPORTING.md` v1 | Required from day 1. Block Kit format §7 of that spec. Tag: `health/v1` |
| Failure DM | Same Slack app, bot token if needed | DMs to `@jroypeterson` on uncaught error |
| Scheduling | GitHub Actions cron in EST-aligned UTC + companion `*-watchdog.yml` recovery (sigma-alert pattern) | One workflow per cadence; watchdog runs hourly during market hours |
| Secrets | Local `.env` via `python-dotenv`; cloud = GH Actions repo secrets | Same pattern |
| Python | 3.12 (sigma-alert), 3.14 available locally | Pin 3.12 for CI parity with sibling projects |
| Tests | `pytest` (every Tier-A project uses it) | Same |

### Confirmed NOT available — not used in any sibling project

- **Polygon, IEX Cloud, Quandl, NewsAPI, OpenAI** — explicitly listed as "not currently used" in `CAPABILITIES.md`. Phase 1 deliberately stays free-tier; if §6 latency math doesn't pencil, Polygon's LULD WebSocket is the obvious paid fallback.
- **No shared Python utility library across projects.** Convention is per-repo modules. sa-monitor will roll its own `markethours.py`, `dedup.py`, etc., and copy the patterns from sigma-alert / earnings_agent rather than importing from them.
- **No existing halt-feed integration anywhere.** Net-new dependency.

### MCP-server constraint (operational)

Per `CAPABILITIES.md` and `feedback_claude_ai_connectors_in_triggers.md`: **scheduled GH Actions runs do not have access to `claude.ai` MCP servers.** All sa-monitor automation must use raw HTTP / webhook / bot-token calls. MCPs are fine for Cowork-driven tasks (this conversation, manual debugging) but not for the runtime worker.

---

## 2. Source feeds — endpoints

Two free, no-auth feeds cover the universe of US equity halts. Both are publicly documented and used by retail data products (StockTitan, OAS, etc.).

### 2.1 Nasdaq Trader Trade Halt RSS

| Field | Value |
|---|---|
| **Documentation** | https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS |
| **Feed URL** | https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts |
| **HTML view** | https://www.nasdaqtrader.com/trader.aspx?id=tradehalts |
| **Format** | RSS 2.0 XML |
| **Auth** | None |
| **Cost** | Free |
| **Coverage** | All SRO-listed US equities — Nasdaq + NYSE + NYSE American + NYSE Arca + Cboe BZX + IEX. Nasdaq operates this feed industry-wide as the UTP/CQS halt-of-record. |
| **ToS** | `nasdaqtrader.com/content/administrationsupport/agreementstrading/THRSSFeedTermsCond.pdf` — free for non-commercial / data-display use. Read before deploying. |

**Item shape (community-reported — confirm against live capture):**

```xml
<item>
  <title>Trade Halt: VRDN</title>
  <description>Issue Symbol: VRDN; Halt Date: 05/05/2026; Halt Time: 06:55:32; Reason Code: T1 (Halt - News Pending); ...</description>
  <pubDate>Tue, 05 May 2026 06:55:35 -0400</pubDate>
  <link>https://www.nasdaqtrader.com/...</link>
  <!-- custom namespaced fields commonly include: -->
  <ndaq:IssueSymbol>VRDN</ndaq:IssueSymbol>
  <ndaq:CompanyName>Viridian Therapeutics, Inc.</ndaq:CompanyName>
  <ndaq:ReasonCode>T1</ndaq:ReasonCode>
  <ndaq:HaltDate>05/05/2026</ndaq:HaltDate>
  <ndaq:HaltTime>06:55:32</ndaq:HaltTime>
  <ndaq:ResumptionDate />
  <ndaq:ResumptionQuoteTime />
  <ndaq:ResumptionTradeTime />
</item>
```

**Behavior to verify against live capture (§7):** does a single item track a halt's full lifecycle (initial halt → resumption populated later) or do halt and resume publish as separate items? Community parsers I've reviewed assume the former, but the actual production code must handle whichever the feed actually does.

### 2.2 NYSE Trade Halt CSV API

| Field | Value |
|---|---|
| **HTML view** | https://www.nyse.com/trade-halt |
| **Current download** | https://www.nyse.com/api/trade-halts/current/download |
| **Historical download** | https://www.nyse.com/api/trade-halts/historical/download?haltDateFrom=YYYY-MM-DD (1 yr lookback) |
| **Format** | CSV (kickoff says JSON — correction: it's CSV) |
| **Auth** | None |
| **Cost** | Free |
| **Coverage** | NYSE, NYSE American, NYSE Arca only. Excludes Nasdaq-listed names. |

**Columns (confirmed from public scrapes):**

```
Halt Date | Halt Time | Symbol | Name | Exchange | Reason | Resume Date | NYSE Resume Time
```

Times in ET. `Resume Date` / `NYSE Resume Time` are blank until the resumption is published.

### 2.3 Why both feeds, not just one

- Nasdaq's RSS technically covers everything (UTP/CQS), but NYSE-listed halt events occasionally appear faster on NYSE's own endpoint by 1–2 seconds (the venues publish to their own surface first, then forward to the consolidated tape).
- Polling both and deduping by `(symbol, halt_date, halt_time)` minimizes single-source latency.
- If one feed is down, the other still produces the alert. Defensive, not redundant.

---

## 3. Reason-code reference table

Authoritative source: https://www.nasdaqtrader.com/trader.aspx?id=tradehaltcodes — Nasdaq publishes the canonical schedule for FINRA/CQS halts. NYSE uses Nasdaq's codes plus a small handful of NYSE-specific reason strings. Below is the union, with Phase 1 alert relevance flagged.

| Code | Meaning | Phase 1 alert? | Notes |
|---|---|---|---|
| **T1** | Halt — News Pending | **Yes** | The flagship SA-equivalent. Most valuable alert. |
| **T2** | Halt — News Released | Yes | Fires when news crosses; pairs with T1 |
| **T5** | Single Stock Trading Pause (10% price change in 5 min) | Yes | LULD-equivalent volatility halt for non-LULD names; rarer post-2014 |
| **T6** | Halt — Extraordinary Market Activity | Yes | Issued when there's likely a misexecution/erroneous trade |
| **T8** | Halt — ETP / EXTL | Optional | ETP-specific; not relevant to single-name coverage |
| **T12** | Halt — Additional Information Requested | Yes | Nasdaq follow-up after a T1, often material |
| **H4** | Halt — Non-Compliance | Yes | Listing-requirement violation |
| **H9** | Halt — Not Current with Filings | Yes | Late 10-K/10-Q etc. |
| **H10** | SEC Trading Suspension | **Yes — high signal** | SEC-initiated, often fraud or pump-and-dump cases. Rare on a healthcare names but always material when it fires |
| **H11** | Halt — Regulatory Concern (other market) | Yes | Cross-exchange regulatory hold |
| **M1** | Corporate Action | Optional | Often M&A close, ticker change, reverse split |
| **M2** | Quotation Not Available | No | Operational, low signal |
| **O1** | Operations Halt — Contact Market Ops | No | Internal Nasdaq |
| **IPO1** | IPO Issue Not Yet Trading | No | First-day IPO, not a halt of an active name |
| **IPOQ** | IPO Quotation Initiated | No | Same |
| **LUDP** | LULD Pause | **Yes** | Limit Up Limit Down volatility halt — most common type during normal trading |
| **LUDS** | LULD Trading Pause — Straddle Condition | Yes | LULD variant when band straddles last trade |
| **MWC1/2/3** | Market-Wide Circuit Breaker (Level 1/2/3) | Always notify | Sector-wide, not single-name; treat as exchange status alert |
| **MWCO/MWCQ** | MWCB-related Quote/Order | Always notify | Same |
| **R4** | Halt — Resumption Trade Time | n/a | Resume marker, not a halt |
| **R1** | Halt — Resumption Quote Time | n/a | Resume marker |

**Phase 1 default filter:** include `T1, T2, T5, T6, T12, H4, H9, H10, H11, M1, LUDP, LUDS` plus any `MWC*` (always notify). Exclude `T8, M2, O1, IPO*` by default but log them for review.

**Human-readable mapping** lives in `src/reason_codes.py` so the alert template can render `T1 - News Pending` rather than just `T1`.

---

## 4. Rate limits, reliability, and latency

### 4.1 Rate limits

Neither feed publishes a formal rate limit. Community scrapers running 24/7 at 5-second polling have been stable for years (NYSE-listed) and at 5–10s for Nasdaq RSS. Recommendation: **5-second poll for both feeds, with exponential backoff on 429/5xx.**

If we ever do trip a rate limit, the symptom is HTTP 429 or a stale `Last-Modified` header. The runner should:
1. Honor `Retry-After` if present
2. Otherwise back off 30s, then 60s, then 120s
3. Post a Slack DM to `@jroypeterson` if backoff persists >5 minutes (we're not getting halts during that window)

### 4.2 Reliability

- **Nasdaq RSS:** highly stable. The feed is part of Nasdaq Trader's public infrastructure and is the same surface industry vendors use.
- **NYSE CSV:** also stable, but the endpoint is technically internal API used by `nyse.com/trade-halt`. Format could change without notice. Defensive: if CSV columns shift, alert via Slack DM and continue with Nasdaq RSS only until fixed.
- **Both:** outages happen ~1–2 times per year per published incident reports. The dual-source design degrades gracefully.

### 4.3 Latency profile (estimated; confirm in §7)

| Stage | Estimated latency |
|---|---|
| Exchange halt → feed publish | 1–3 seconds (both feeds) |
| Feed publish → our poll detects | 0–5 seconds (5s poll cadence) |
| Detection → Slack post | 200–500 ms (network + Slack render) |
| **Total: halt event → Slack message** | **~2–9 seconds typical** |

StreetAccount editorial latency on halt alerts is anecdotally 5–15 seconds (their alerts post within seconds of the halt notice). **The 30-second kickoff target is comfortably achievable** assuming polling is the bottleneck, not the feed itself. **No relaxed acceptance criterion needed** — the kickoff's "or relax if data sources don't physically support" branch doesn't apply.

The one scenario where we'd be slower than SA: SA might have CTA Direct or NYSE Pillar entitlement giving them sub-second halt events from the SIP. We don't, and can't without paying. If post-acceptance-test we're consistently 5s+ behind SA, that's the answer for why and the next move would be a Polygon LULD WebSocket subscription (~$200–$300/mo) or accept SA's structural lead.

---

## 5. Polling vs WebSocket — recommendation

**Recommendation: poll both feeds at 5-second cadence. No WebSocket.**

| Factor | Polling (recommended) | WebSocket (Polygon, $$$) |
|---|---|---|
| Cost | $0 | ~$200–$300/mo |
| Setup | `requests.get()` + `feedparser` for RSS, `csv` stdlib for NYSE | New SDK, auth, reconnect logic |
| Latency floor | ~5s (poll cadence) | Sub-second |
| GH Actions compatibility | Native | Requires long-lived runner — Actions cron is too coarse for WS |
| Reliability | Two independent sources | One vendor; Polygon outages = our outages |
| Phase 1 fit | Excellent — 30s target with 9s headroom | Overkill; deferred to Phase 1.5 if SA consistently beats us |

GH Actions cron's minimum schedule is 1 minute — too coarse for halt monitoring. **Phase 1 will use a long-running Python process** (similar to a small daemon) deployed somewhere that supports continuous execution. Two options:

1. **GitHub Actions with a 5h45m cap loop** — workflow runs from 09:25 ET to ~16:10 ET, polls in a loop with 5s sleep. Stops gracefully before the 6h job timeout. New workflow fires the next day. **Recommended for Phase 1 simplicity.**
2. **Self-hosted runner (Windows machine or cheap VPS)** — true 24/5 daemon. Better latency floor by ~1s but adds machine ops. Defer to Phase 2 if needed.

The kickoff explicitly mentions option (2) as a fallback ("may need to document a self-hosted runner option if Actions cron isn't fast enough"). Phase 1 starts with (1).

---

## 6. Coverage filter — applied at the worker (LOCKED)

Per the 2026-05-05 sign-off:

- Read `Coverage Manager/exports/universe.csv` + `universe_metadata.json` at process startup
- **Biopharma exclusion (locked 2026-05-05):** drop `Subsector (JP) == "Biotech"` AND drop `Sector (JP) == "Biopharma"` rows with blank Subsector (Coverage Manager has 57 unclassified Biopharma rows; about 25 are unclassified biotechs by inspection, the rest have data quality issues — see `coverage-manager-issue-draft.md`). Keep Large Pharma + Specialty/Generic Pharma + all MedTech + all HC Services + all non-HC sectors. **Net coverage = 554 tickers** as built by D2.
- Halt event passes filter iff `event.symbol ∈ filtered_universe`
- Sector + subsector tags ride along into the Slack message footer (replaces SA's `Portfolio` line):

```
Sector: MedTech / Diagnostics
```

---

## 7. Sample captures — STUBBED pending egress allowlist

The kickoff requires "two example halt events from each feed (real captures, with timestamps)." This Cowork sandbox blocks egress to `nasdaqtrader.com` and `nyse.com` (see Settings → Capabilities → Network). Fastest unblock paths in order of preference:

1. **Whitelist both domains in cowork settings.** ~30 seconds. I capture the samples in a follow-up message and inline them here.
2. **Run the prototype on the local Windows machine** once D2 is signed off. I capture from the prototype's first hour-of-market run.
3. **Pull from a secondary source** (e.g., StockTitan's halt tracker or a GitHub historical halt dump). Less authoritative; only if (1) and (2) are blocked.

Until then, this section is a STUB.

```
Nasdaq RSS — Example 1: <pending>
Nasdaq RSS — Example 2: <pending>
NYSE CSV — Example 1: <pending>
NYSE CSV — Example 2: <pending>
```

I'll fill these and re-issue D1 for review once unblocked.

---

## 8. Routing decisions summary

These are the decisions D1 locks in (subject to your sign-off). D4 onward depends on them.

1. **Both Nasdaq RSS + NYSE CSV.** Polling, 5-second cadence, dedupe by `(symbol, halt_date, halt_time)`.
2. **Free tier only for Phase 1.** No Polygon. Revisit only if acceptance-test latency is consistently >SA by 5+ seconds.
3. **GH Actions long-running job** (option 1 in §5), one workflow per market session. Self-hosted runner deferred.
4. **Filter against Coverage Manager's `exports/`.** Locked exclusion rule per §6.
5. **Slack delivery via new webhook on the existing earnings-agent app.** Single consolidated channel `#street-account` for all sa-monitor alerts across Phases 1–5. Env var `SLACK_WEBHOOK_STREET_ACCOUNT`. Supersedes the kickoff's 5-channel split — operational simplification per 2026-05-05 sign-off; if volume becomes unworkable post-Phase 2, we can re-fragment.
6. **Health heartbeat to `#status-reports` per `HEALTH_REPORTING.md` v1**, Block Kit format, tag `health/v1`.
7. **Reason-code human-readable mapping** lives in `src/reason_codes.py` (Phase 1 default filter §3).
8. **Resumption events** tracked under same dedupe key; emit a separate Slack message per the kickoff's "Resume notification" template.

---

## 9. Open questions — RESOLVED 2026-05-05

1. **Biopharma exclusion** — **lenient + tightened.** Drop `Subsector == "Biotech"` AND drop blank-Subsector Biopharma. **554 tickers.** (§6)
2. **Egress allowlist** — pending workspace fix. Specific hosts to add: `nasdaqtrader.com`, `nyse.com`. (§7)
3. **`#street-account` channel** — create in JP Personal Hub workspace; one channel for all sa-monitor alerts across Phases 1–5.
4. **Slack app** — reuse "Earnings Agent Bot." New webhook env var: `SLACK_WEBHOOK_STREET_ACCOUNT`.
5. **GH repo** — create `jroypeterson/sa-monitor`, mirror sigma-alert layout.

## 10. D2 file naming

Kickoff names D2 `coverage-portfolios.json` based on its now-discarded 5-portfolio mental model. Renaming to `sa_monitor_universe.json` to match the actual schema (sector/subsector tags, no portfolio mapping). Will note this shift in D2's sample DM and in the eventual README.
