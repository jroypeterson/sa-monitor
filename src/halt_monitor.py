"""Phase 1 sa-monitor halt-feed runner (D4 + D5 + D6 wired).

Polls NYSE LULD CSV and Nasdaq Trader RSS at 5-second cadence, filters halts
to the sa-monitor coverage universe, dedupes by halt-id, renders to stdout
in the sa-monitor template, and (when --slack live) posts to #street-account.

D6 additions:
- Persistent halt-id state (state/dedup_state_<YYYY-MM-DD>.json) so a runner
  restart mid-session doesn't re-fire previously-seen halts.
- Failure DMs to #street-account when a feed has N consecutive fetch errors.
- Final health heartbeat on graceful shutdown (per HEALTH_REPORTING.md v1).
- Structured JSONL event log of every emit decision.

Run:
    python -m src.halt_monitor --slack live --duration 3600 --log logs/run.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import slack, state
from .calendars import AnalystDayCalendar, EarningsCalendar
from .coverage import Universe
from .dedup import HaltTracker
from .enrichment import build_note_context
from .feeds import nasdaq, nyse
from .feeds.types import HaltEvent
from .news import bw, gnw, prnewswire
from .news.cache import NewsCache
from .reason_codes import is_phase1_emit_code
from .template import render_halt, render_resume

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("halt_monitor")

# After this many consecutive failures on a single feed we DM the user.
# At 5s polling, 60 = ~5 minutes of a feed being unavailable.
FAILURE_DM_THRESHOLD = 60

# News feeds are slower-moving and rate-conscious — poll every Nth halt
# tick rather than every tick. At 5s halt cadence, NEWS_POLL_EVERY=6 means
# news refreshes every ~30s.
NEWS_POLL_EVERY = 6


@dataclass
class FeedHealth:
    """Per-feed runtime health for the failure-DM logic."""
    consecutive_failures: int = 0
    failure_dm_sent: bool = False  # don't spam — one DM per outage
    last_error: str = ""


@dataclass
class RunStats:
    started_at: str
    polls_completed: int = 0
    fetch_errors: int = 0
    nasdaq_events_seen: int = 0
    nyse_events_seen: int = 0
    halts_emitted: int = 0
    resumes_emitted: int = 0
    halts_filtered_out_of_universe: int = 0
    halts_filtered_non_emit_code: int = 0
    halts_enriched_with_note: int = 0
    halts_enriched_with_cross_ref: int = 0
    slack_posts_succeeded: int = 0
    slack_posts_failed: int = 0
    state_loads: int = 0
    state_saves: int = 0
    earnings_calendar_loaded: int = 0
    earnings_calendar_generated_at: Optional[str] = None
    analyst_days_calendar_loaded: int = 0
    analyst_days_calendar_generated_at: Optional[str] = None
    news_polls_completed: int = 0
    news_items_ingested: int = 0
    news_cache_size: int = 0
    feed_health: dict = field(default_factory=lambda: {
        "nasdaq_rss": asdict(FeedHealth()),
        "nyse_csv": asdict(FeedHealth()),
        "news_prnewswire": asdict(FeedHealth()),
        "news_businesswire": asdict(FeedHealth()),
        "news_globenewswire": asdict(FeedHealth()),
    })


_should_stop = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _should_stop
    log.warning("received signal %s; stopping after current poll", signum)
    _should_stop = True


def _safe_fetch(name: str, fetch_fn, stats: RunStats,
                health: dict[str, FeedHealth],
                slack_mode: str) -> list[HaltEvent]:
    """Wrap a feed fetch so a single error doesn't kill the loop.
    Tracks consecutive failures per feed; fires a Slack DM when threshold hit."""
    try:
        events = fetch_fn()
        h = health[name]
        if h.consecutive_failures > 0:
            log.info("%s: recovered after %d consecutive failures",
                     name, h.consecutive_failures)
            h.consecutive_failures = 0
            h.failure_dm_sent = False
            h.last_error = ""
        return events
    except Exception as exc:
        stats.fetch_errors += 1
        h = health[name]
        h.consecutive_failures += 1
        h.last_error = str(exc)
        log.error("%s fetch failed (%d consecutive): %s",
                  name, h.consecutive_failures, exc)

        if (h.consecutive_failures >= FAILURE_DM_THRESHOLD
                and not h.failure_dm_sent
                and slack_mode == "live"):
            try:
                slack.post_dm(
                    f"feed `{name}` has failed {h.consecutive_failures} consecutive "
                    f"polls (~{h.consecutive_failures * 5 // 60} min). Last error: "
                    f"`{h.last_error[:200]}`",
                    level="error",
                )
                h.failure_dm_sent = True
                log.warning("%s: failure DM sent", name)
            except Exception as dm_exc:
                log.error("%s: failed to send failure DM: %s", name, dm_exc)
        return []


def _emit(
    kind: str,
    event: HaltEvent,
    universe: Universe,
    log_path: Optional[Path],
    *,
    include_non_emit: bool,
    stats: RunStats,
    slack_mode: str = "off",
    slack_webhook_url: Optional[str] = None,
    earnings_calendar: Optional[EarningsCalendar] = None,
    analyst_days_calendar: Optional[AnalystDayCalendar] = None,
    news_cache: Optional[NewsCache] = None,
) -> None:
    """Filter, render, and emit one halt or resume event."""
    meta = universe.get(event.symbol)
    if meta is None:
        stats.halts_filtered_out_of_universe += 1
        log.debug("skip out-of-universe: %s", event)
        return

    if not include_non_emit and not is_phase1_emit_code(event.reason_code):
        stats.halts_filtered_non_emit_code += 1
        log.info("skip non-emit code %s for %s (logged only)",
                 event.reason_code, event.symbol)
        if log_path:
            _append_log(log_path, kind, event, meta, emitted=False)
        return

    note_context: Optional[str] = None
    if kind == "halt" and (earnings_calendar is not None
                            or analyst_days_calendar is not None
                            or news_cache is not None):
        note_context = build_note_context(
            event,
            earnings=earnings_calendar,
            analyst_days=analyst_days_calendar,
            news_cache=news_cache,
        )
        if note_context:
            stats.halts_enriched_with_note += 1
            if note_context.startswith("Follows "):
                stats.halts_enriched_with_cross_ref += 1
            log.info("enriched %s with note: %s", event.symbol, note_context)

    if kind == "halt":
        stats.halts_emitted += 1
        rendered = render_halt(event, sector=meta.sector,
                               subsector=meta.subsector, name_override=meta.name,
                               note_context=note_context)
    elif kind == "resume":
        stats.resumes_emitted += 1
        rendered = render_resume(event, sector=meta.sector,
                                 subsector=meta.subsector, name_override=meta.name)
    else:
        log.error("unknown emit kind: %s", kind)
        return

    print()
    print("=" * 60)
    print(rendered)
    print("=" * 60)
    sys.stdout.flush()

    if slack_mode != "off":
        try:
            if kind == "halt":
                slack.post_halt(event, meta, webhook_url=slack_webhook_url,
                                dry_run=(slack_mode == "dry-run"),
                                note_context=note_context)
            else:
                slack.post_resume(event, meta, webhook_url=slack_webhook_url,
                                  dry_run=(slack_mode == "dry-run"))
            stats.slack_posts_succeeded += 1
        except Exception as exc:
            stats.slack_posts_failed += 1
            log.error("slack post failed for %s: %s", event.symbol, exc)

    if log_path:
        _append_log(log_path, kind, event, meta, emitted=True, note_context=note_context)


def _append_log(log_path: Path, kind: str, event: HaltEvent, meta,
                *, emitted: bool, note_context: Optional[str] = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "emitted": emitted,
        "symbol": event.symbol,
        "exchange": event.exchange,
        "halt_date": event.halt_date,
        "halt_time": event.halt_time,
        "reason_code": event.reason_code,
        "reason_description": event.reason_description,
        "resume_trade_time": event.resume_trade_time,
        "source": event.source,
        "sector": meta.sector if meta else None,
        "subsector": meta.subsector if meta else None,
        "note_context": note_context,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _post_health_heartbeat(stats: RunStats, slack_mode: str,
                            ended_with_error: bool = False) -> None:
    """End-of-run heartbeat to #street-account per HEALTH_REPORTING.md.
    Only fires in slack live mode."""
    if slack_mode != "live":
        return
    status = "error" if ended_with_error else "ok"
    if stats.fetch_errors > 0 and not ended_with_error:
        status = "warning"

    parts = [
        f"halt-monitor run summary: polls={stats.polls_completed}",
        f"halts={stats.halts_emitted}",
        f"resumes={stats.resumes_emitted}",
        f"slack_ok/fail={stats.slack_posts_succeeded}/{stats.slack_posts_failed}",
        f"fetch_errors={stats.fetch_errors}",
    ]
    if (stats.earnings_calendar_loaded or stats.analyst_days_calendar_loaded
            or stats.news_polls_completed):
        enrich_bits = [f"enriched={stats.halts_enriched_with_note}"]
        if stats.halts_enriched_with_cross_ref:
            enrich_bits.append(f"cross_ref={stats.halts_enriched_with_cross_ref}")
        sources = []
        if stats.earnings_calendar_loaded:
            sources.append(
                f"earnings={stats.earnings_calendar_loaded}@{stats.earnings_calendar_generated_at or '?'}"
            )
        if stats.analyst_days_calendar_loaded:
            sources.append(
                f"analyst_days={stats.analyst_days_calendar_loaded}@{stats.analyst_days_calendar_generated_at or '?'}"
            )
        if stats.news_polls_completed:
            sources.append(
                f"news_cache={stats.news_cache_size} ({stats.news_polls_completed} polls)"
            )
        parts.append(" ".join(enrich_bits) + " (" + ", ".join(sources) + ")")
    summary = ", ".join(parts[:5]) + (" — " + parts[5] if len(parts) > 5 else "")
    try:
        slack.post_dm(summary, level=status if status in {"ok","warning","error"} else "warning")
    except Exception as exc:
        log.error("failed to post health heartbeat: %s", exc)


def run(
    *,
    once: bool = False,
    duration_sec: Optional[int] = None,
    interval_sec: int = 5,
    log_path: Optional[Path] = None,
    include_non_emit: bool = False,
    universe_path: Optional[Path] = None,
    slack_mode: str = "off",
    slack_webhook_url: Optional[str] = None,
    persist_state: bool = True,
    earnings_calendar_path: Optional[Path] = None,
    analyst_days_calendar_path: Optional[Path] = None,
    enable_news_cross_ref: bool = False,
    news_window_minutes: int = 60,
) -> RunStats:
    universe = Universe(universe_path) if universe_path else Universe()
    log.info("loaded universe: %d tickers (%s)", len(universe), universe.filter_rule)
    log.info("slack_mode=%s persist_state=%s", slack_mode, persist_state)

    earnings_calendar = (
        EarningsCalendar(earnings_calendar_path) if earnings_calendar_path else None
    )
    analyst_days_calendar = (
        AnalystDayCalendar(analyst_days_calendar_path) if analyst_days_calendar_path else None
    )
    if earnings_calendar is not None:
        log.info("earnings calendar: %d events (generated_at=%s)",
                 earnings_calendar.loaded_count, earnings_calendar.generated_at)
    if analyst_days_calendar is not None:
        log.info("analyst-days calendar: %d events (generated_at=%s)",
                 analyst_days_calendar.loaded_count, analyst_days_calendar.generated_at)

    news_cache: Optional[NewsCache] = (
        NewsCache(window_minutes=news_window_minutes) if enable_news_cross_ref else None
    )
    if news_cache is not None:
        log.info("news cross-ref enabled (window=%dm, sources=PRN/BW/GNW)", news_window_minutes)

    if persist_state:
        state.cleanup_old()
        tracker = state.load()
    else:
        tracker = HaltTracker()

    stats = RunStats(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    stats.state_loads = 1 if persist_state else 0
    if earnings_calendar is not None:
        stats.earnings_calendar_loaded = earnings_calendar.loaded_count
        stats.earnings_calendar_generated_at = earnings_calendar.generated_at
    if analyst_days_calendar is not None:
        stats.analyst_days_calendar_loaded = analyst_days_calendar.loaded_count
        stats.analyst_days_calendar_generated_at = analyst_days_calendar.generated_at
    health = {name: FeedHealth(**stats.feed_health[name])
              for name in stats.feed_health}

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    deadline = (time.monotonic() + duration_sec) if duration_sec else None
    ended_with_error = False

    try:
        while not _should_stop:
            t0 = time.monotonic()

            nasdaq_events = _safe_fetch("nasdaq_rss", nasdaq.fetch, stats, health, slack_mode)
            nyse_events = _safe_fetch("nyse_csv", nyse.fetch, stats, health, slack_mode)
            stats.nasdaq_events_seen = max(stats.nasdaq_events_seen, len(nasdaq_events))
            stats.nyse_events_seen = max(stats.nyse_events_seen, len(nyse_events))

            # News-feed poll (slower cadence than halt feeds — every Nth tick).
            # Run BEFORE halt emit so a halt fired this tick can cross-ref news
            # already in the cache from this poll.
            if news_cache is not None and stats.polls_completed % NEWS_POLL_EVERY == 0:
                news_items: list = []
                for label, mod in [("news_prnewswire", prnewswire),
                                    ("news_businesswire", bw),
                                    ("news_globenewswire", gnw)]:
                    news_items.extend(_safe_fetch(label, mod.fetch, stats, health, slack_mode))
                added = news_cache.ingest(news_items)
                stats.news_polls_completed += 1
                stats.news_items_ingested += added
                # tickers_indexed reflects items currently in the lookback
                # window (i.e. cross-refable). news_items_ingested is the
                # cumulative count for dedup auditing.
                stats.news_cache_size = news_cache.tickers_indexed

            for kind, event in tracker.ingest(nasdaq_events + nyse_events):
                _emit(kind, event, universe, log_path,
                      include_non_emit=include_non_emit, stats=stats,
                      slack_mode=slack_mode, slack_webhook_url=slack_webhook_url,
                      earnings_calendar=earnings_calendar,
                      analyst_days_calendar=analyst_days_calendar,
                      news_cache=news_cache)

            if persist_state:
                try:
                    state.save(tracker)
                    stats.state_saves += 1
                except Exception as exc:
                    log.error("state save failed: %s", exc)

            stats.polls_completed += 1
            if stats.polls_completed % 12 == 0:
                log.info("poll %d: tracked=%d emit=%d/%d errors=%d",
                         stats.polls_completed, len(tracker),
                         stats.halts_emitted, stats.resumes_emitted, stats.fetch_errors)

            if once:
                break
            if deadline and time.monotonic() >= deadline:
                log.info("duration reached; stopping")
                break

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval_sec - elapsed))
    except Exception as exc:
        ended_with_error = True
        log.exception("run aborted: %s", exc)
        if slack_mode == "live":
            try:
                slack.post_dm(f"halt-monitor crashed: `{exc}`", level="error")
            except Exception:
                pass
        raise
    finally:
        # Persist health snapshot back into stats for the final report
        for name, h in health.items():
            stats.feed_health[name] = asdict(h)
        log.info("run ended: polls=%d halts=%d resumes=%d errors=%d",
                 stats.polls_completed, stats.halts_emitted,
                 stats.resumes_emitted, stats.fetch_errors)
        _post_health_heartbeat(stats, slack_mode, ended_with_error=ended_with_error)

    return stats


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="sa-monitor halt feed runner")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument(
        "--log", type=Path,
        default=Path("logs") / f"halt_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )
    parser.add_argument("--include-non-emit", action="store_true")
    parser.add_argument("--universe", type=Path, default=None)
    parser.add_argument("--slack", choices=["off", "dry-run", "live"], default="off")
    parser.add_argument("--no-persist", action="store_true",
                        help="disable dedup-state persistence (default: enabled)")
    parser.add_argument("--earnings-calendar", type=Path, default=None,
                        help="path to earnings-agent upcoming_events.json (Phase 2 enrichment)")
    parser.add_argument("--analyst-days-calendar", type=Path, default=None,
                        help="path to analyst-days upcoming_events.json (Phase 2 enrichment)")
    parser.add_argument("--news-cross-ref", action="store_true",
                        help="enable PRN/BW/GNW news cross-ref enrichment (Phase 2 slice 2B)")
    parser.add_argument("--news-window-minutes", type=int, default=60,
                        help="lookback window for news cross-ref (default 60min)")
    args = parser.parse_args(argv)

    stats = run(
        once=args.once, duration_sec=args.duration, interval_sec=args.interval,
        log_path=args.log, include_non_emit=args.include_non_emit,
        universe_path=args.universe, slack_mode=args.slack,
        persist_state=not args.no_persist,
        earnings_calendar_path=args.earnings_calendar,
        analyst_days_calendar_path=args.analyst_days_calendar,
        enable_news_cross_ref=args.news_cross_ref,
        news_window_minutes=args.news_window_minutes,
    )
    print(json.dumps(asdict(stats), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
