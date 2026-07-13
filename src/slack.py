"""Slack delivery for sa-monitor halt + resume notifications.

Posts to the consolidated #street-account channel for ALL sa-monitor alerts
across Phases 1-5. Block Kit format per HEALTH_REPORTING.md §4.1.

Webhook source-of-truth:
- SLACK_WEBHOOK_STREET_ACCOUNT env var, OR
- Claude Folder/.secrets/slack_webhook_street_account.txt (one line)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

from .coverage import TickerMeta
from .events.types import (
    CLEARANCE,
    CRL,
    DIR_MET,
    DIR_MISSED,
    FDA_APPROVAL,
    TRIAL_READOUT,
    HCEvent,
)
from .feeds.types import HaltEvent
from .news.types import NewsItem
from .template import (
    _NEWS_SOURCE_LABELS,
    _format_date_short,
    _format_price,
    _format_time_hhmm,
    biotech_triage_cta,
    followup_headline,
    followup_source_label,
    followup_when,
    hc_event_cta_context,
    hc_event_headline,
    hc_event_when,
    is_biotech,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_FOLDER = REPO_ROOT.parent
WEBHOOK_FILE = CLAUDE_FOLDER / ".secrets" / "slack_webhook_street_account.txt"
ENV_VAR = "SLACK_WEBHOOK_STREET_ACCOUNT"

POST_TIMEOUT_SEC = 10
SLACK_SECTION_TEXT_LIMIT = 3000

# Backoff for the wake-race: a scheduled task that catches up on wake
# (StartWhenAvailable) can fire before DNS/WiFi is up, so the first POST dies
# with a transient transport error. Retry rides through it. See CONVENTIONS s3.
_RETRY_BACKOFF = (5, 15, 30)  # seconds to wait BEFORE retry attempts 2..N


def resolve_webhook_url(env_var: str = ENV_VAR,
                        file_path: Path = WEBHOOK_FILE) -> str:
    env = os.environ.get(env_var)
    if env:
        return env.strip()
    if file_path.exists():
        return file_path.read_text(encoding="utf-8").strip()
    raise SystemExit(
        f"No Slack webhook configured. Set the {env_var} env var or write the "
        f"webhook URL (one line) to {file_path}."
    )


def build_halt_blocks(event: HaltEvent, meta: Optional[TickerMeta],
                      *, note_context: Optional[str] = None) -> dict:
    name = (meta.name if meta else "") or event.name or event.symbol
    date_short = _format_date_short(event.halt_date)
    time_hhmm = _format_time_hhmm(event.halt_time)

    headline = f":no_entry: *SA:* `{event.symbol}` — {name} halted, news pending"
    if event.last_price is not None:
        headline += f"  ·  {_format_price(event.last_price)}"

    reason_line = (
        f"`{time_hhmm} ET {date_short}`  ·  reason `{event.reason_code} - "
        f"{event.reason_description}`"
    )
    if meta and meta.sector:
        sector_str = meta.sector
        if meta.subsector:
            sector_str += f" / {meta.subsector}"
        reason_line += f"  ·  Sector: {sector_str}"

    source_line = f"_source: {event.source} ({event.exchange})_"
    lines = [headline, reason_line]
    if note_context:
        lines.append(f"_{note_context}_")
    # Lean halt->triage hand-off (option A): biotech halts carry a copy-pasteable
    # triage nudge. See root biotech_catalyst_architecture_plan.md §3.
    if meta and is_biotech(meta.subsector):
        lines.append(biotech_triage_cta(event.symbol))
    lines.append(source_line)
    text_block = "\n".join(lines)
    fallback = (
        f"SA: {event.symbol} {name} halted, news pending "
        f"({event.reason_code} - {event.reason_description})"
    )
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_block[:SLACK_SECTION_TEXT_LIMIT]},
            }
        ],
        "text": fallback,
    }


def build_resume_blocks(event: HaltEvent, meta: Optional[TickerMeta]) -> dict:
    name = (meta.name if meta else "") or event.name or event.symbol
    date_short = _format_date_short(event.halt_date)
    halt_hhmm = _format_time_hhmm(event.halt_time)
    resume_hhmm = _format_time_hhmm(event.resume_trade_time or "")

    headline = (
        f":white_check_mark: *SA:* `{event.symbol}` — shares to resume trading "
        f"at {resume_hhmm} ET"
    )
    detail = (
        f"`{date_short}`  ·  resume `{resume_hhmm} ET`  ·  originally halted "
        f"`{halt_hhmm} ET`  ·  reason `{event.reason_code} - "
        f"{event.reason_description}`"
    )
    if meta and meta.sector:
        sector_str = meta.sector
        if meta.subsector:
            sector_str += f" / {meta.subsector}"
        detail += f"  ·  Sector: {sector_str}"

    source_line = f"_source: {event.source} ({event.exchange})_"
    text_block = "\n".join([headline, detail, source_line])
    fallback = (
        f"SA: {event.symbol} resume at {resume_hhmm} ET (originally halted "
        f"{halt_hhmm} ET, {event.reason_code})"
    )
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_block[:SLACK_SECTION_TEXT_LIMIT]},
            }
        ],
        "text": fallback,
    }


def build_followup_blocks(halt: HaltEvent, item: NewsItem,
                          meta: Optional[TickerMeta], *,
                          last_price: Optional[float] = None) -> dict:
    """Block Kit for a §7 Follow-up alert — the substantive news that broke on a
    previously-halted covered name. Mirrors build_halt_blocks; references the
    original halt in-body (no Slack threading over a webhook)."""
    symbol = halt.symbol
    name = (meta.name if meta else "") or halt.name or symbol
    time_hhmm, date_short = followup_when(halt, item)
    headline = followup_headline(item)

    header = f":newspaper: *SA:* `{symbol}` — Follow-up: {headline}"
    price = last_price if last_price is not None else halt.last_price
    if price is not None:
        header += f"  ·  {_format_price(price)}"

    halt_hhmm = _format_time_hhmm(halt.halt_time)
    detail = f"`{time_hhmm} ET {date_short}`  ·  Follows the {halt_hhmm} ET halt on `{symbol}`"
    if meta and meta.sector:
        sector_str = meta.sector
        if meta.subsector:
            sector_str += f" / {meta.subsector}"
        detail += f"  ·  Sector: {sector_str}"

    source_line = f"_source: {followup_source_label(item)} press release_"
    text_block = "\n".join([header, detail, source_line])
    fallback = f"SA: {symbol} Follow-up: {headline}"
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_block[:SLACK_SECTION_TEXT_LIMIT]},
            }
        ],
        "text": fallback,
    }


def _hc_event_emoji(event: HCEvent) -> str:
    """Event-type emoji per design §5. Trial readouts split on direction so a
    'met' and a 'missed' are visually distinct at a glance."""
    if event.event_type == FDA_APPROVAL:
        return ":pill:"
    if event.event_type == CRL:
        return ":x:"
    if event.event_type == CLEARANCE:
        return ":heavy_check_mark:"
    if event.event_type == TRIAL_READOUT:
        if event.direction == DIR_MISSED:
            return ":small_red_triangle_down:"
        if event.direction == DIR_MET:
            return ":test_tube:"
        return ":microscope:"  # topline, direction TBD
    return ":pill:"


def build_hc_event_blocks(event: HCEvent, meta: Optional[TickerMeta]) -> dict:
    """Block Kit for an HC event-wire alert — an FDA action or clinical readout
    on a covered name (design §5, templates §15/§16/§19). Single-section mrkdwn,
    mirroring build_followup_blocks. Headline is the issuer's verbatim title;
    the fact-dense efficacy body is a deferred LLM enhancement."""
    symbol = event.symbol
    headline = hc_event_headline(event.headline)
    time_hhmm, date_short = hc_event_when(event.published_at)

    header = f"{_hc_event_emoji(event)} *SA:* `{symbol}` — {headline}"

    when = f"`{time_hhmm} ET {date_short}`" if time_hhmm else ""
    detail_bits = [when] if when else []
    if meta and meta.sector:
        sector_str = meta.sector
        if meta.subsector:
            sector_str += f" / {meta.subsector}"
        detail_bits.append(f"Sector: {sector_str}")
    detail = "  ·  ".join(detail_bits)

    label = _NEWS_SOURCE_LABELS.get(event.source, event.source)
    source_line = f"_source: {label} press release"
    if event.url:
        source_line += f" · {event.url}"
    source_line += "_"

    lines = [header]
    if detail:
        lines.append(detail)
    if meta and is_biotech(meta.subsector):
        lines.append(biotech_triage_cta(symbol, context=hc_event_cta_context(event)))
    lines.append(source_line)
    text_block = "\n".join(lines)
    fallback = f"SA: {symbol} — {headline}"
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_block[:SLACK_SECTION_TEXT_LIMIT]},
            }
        ],
        "text": fallback,
    }


def build_dm_blocks(message: str, *, level: str = "warning") -> dict:
    emoji = {"ok": ":white_check_mark:", "warning": ":warning:", "error": ":x:"}.get(
        level, ":warning:"
    )
    text = f"{emoji} *sa-monitor*: {message}"
    return {
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        "text": f"sa-monitor: {message}",
    }


def post_payload(payload: dict, *, webhook_url: Optional[str] = None,
                 timeout: int = POST_TIMEOUT_SEC) -> requests.Response:
    url = webhook_url or resolve_webhook_url()
    headers = {"Content-Type": "application/json"}
    log.debug("slack: POST (url redacted)")
    body = json.dumps(payload)
    # Retry only transient transport errors (DNS-not-ready on wake, etc.); a
    # successful-but-bad-status response is left to raise_for_status as before.
    attempts = len(_RETRY_BACKOFF) + 1
    last_exc = None
    for i in range(attempts):
        try:
            resp = requests.post(url, headers=headers, data=body, timeout=timeout)
            break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if i == attempts - 1:
                raise
            delay = _RETRY_BACKOFF[i]
            log.warning("slack: POST attempt %d/%d failed (%s); retrying in %ds",
                        i + 1, attempts, exc, delay)
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                time.sleep(delay)
    resp.raise_for_status()
    return resp


def post_halt(event: HaltEvent, meta: Optional[TickerMeta], *,
              webhook_url: Optional[str] = None,
              dry_run: bool = False,
              note_context: Optional[str] = None) -> Optional[dict]:
    payload = build_halt_blocks(event, meta, note_context=note_context)
    if dry_run:
        log.info("slack[dry-run] halt payload for %s:\n%s", event.symbol,
                 json.dumps(payload, indent=2))
        return payload
    post_payload(payload, webhook_url=webhook_url)
    return payload


def post_resume(event: HaltEvent, meta: Optional[TickerMeta], *,
                webhook_url: Optional[str] = None,
                dry_run: bool = False) -> Optional[dict]:
    payload = build_resume_blocks(event, meta)
    if dry_run:
        log.info("slack[dry-run] resume payload for %s:\n%s", event.symbol,
                 json.dumps(payload, indent=2))
        return payload
    post_payload(payload, webhook_url=webhook_url)
    return payload


def post_followup(halt: HaltEvent, item: NewsItem, meta: Optional[TickerMeta], *,
                  webhook_url: Optional[str] = None,
                  dry_run: bool = False,
                  last_price: Optional[float] = None) -> Optional[dict]:
    payload = build_followup_blocks(halt, item, meta, last_price=last_price)
    if dry_run:
        log.info("slack[dry-run] followup payload for %s:\n%s", halt.symbol,
                 json.dumps(payload, indent=2))
        return payload
    post_payload(payload, webhook_url=webhook_url)
    return payload


def post_hc_event(event: HCEvent, meta: Optional[TickerMeta], *,
                  webhook_url: Optional[str] = None,
                  dry_run: bool = False) -> Optional[dict]:
    payload = build_hc_event_blocks(event, meta)
    if dry_run:
        log.info("slack[dry-run] hc_event payload for %s:\n%s", event.symbol,
                 json.dumps(payload, indent=2))
        return payload
    post_payload(payload, webhook_url=webhook_url)
    return payload


def post_dm(message: str, *, level: str = "warning",
            webhook_url: Optional[str] = None,
            dry_run: bool = False) -> Optional[dict]:
    payload = build_dm_blocks(message, level=level)
    if dry_run:
        log.info("slack[dry-run] dm payload:\n%s", json.dumps(payload, indent=2))
        return payload
    post_payload(payload, webhook_url=webhook_url)
    return payload
