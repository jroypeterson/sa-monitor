"""Tests for the Slack delivery module."""
from unittest.mock import MagicMock, patch

import pytest

from src.coverage import TickerMeta
from src.feeds.types import HaltEvent
from src.news.types import NewsItem
from src.slack import (
    build_dm_blocks,
    build_followup_blocks,
    build_halt_blocks,
    build_resume_blocks,
    post_followup,
    post_halt,
    post_payload,
    post_resume,
    resolve_webhook_url,
)


def make_event(**overrides):
    defaults = dict(
        symbol="VRDN",
        exchange="Nasdaq",
        halt_date="2026-05-05",
        halt_time="06:55:32",
        reason_code="T1",
        reason_description="News Pending",
        name="Viridian Therapeutics",
        last_price=14.06,
        source="nasdaq_rss",
    )
    defaults.update(overrides)
    return HaltEvent(**defaults)


def make_meta(**overrides):
    defaults = dict(
        symbol="VRDN",
        name="Viridian Therapeutics Inc",
        sector="MedTech",
        subsector="Diagnostics",
    )
    defaults.update(overrides)
    return TickerMeta(**defaults)


def test_halt_blocks_have_required_fields():
    payload = build_halt_blocks(make_event(), make_meta())
    assert "blocks" in payload
    assert "text" in payload
    assert payload["blocks"][0]["type"] == "section"
    assert payload["blocks"][0]["text"]["type"] == "mrkdwn"


def test_halt_blocks_include_ticker_and_name():
    payload = build_halt_blocks(make_event(), make_meta())
    text = payload["blocks"][0]["text"]["text"]
    assert "*SA:* `VRDN`" in text
    assert "Viridian Therapeutics Inc" in text


def test_halt_blocks_use_no_entry_emoji():
    payload = build_halt_blocks(make_event(), make_meta())
    assert ":no_entry:" in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_include_reason():
    payload = build_halt_blocks(make_event(), make_meta())
    assert "T1 - News Pending" in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_include_sector():
    payload = build_halt_blocks(make_event(), make_meta())
    assert "Sector: MedTech / Diagnostics" in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_omit_sector_without_meta():
    payload = build_halt_blocks(make_event(), None)
    assert "Sector:" not in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_biotech_include_triage_cta():
    """Biotech halts carry the copy-pasteable triage nudge (option A, 2026-06-16)."""
    payload = build_halt_blocks(make_event(), make_meta(subsector="Biotech"))
    text = payload["blocks"][0]["text"]["text"]
    assert "Biotech halt — triage this name?" in text
    assert "`triage VRDN`" in text


def test_halt_blocks_non_biotech_omit_triage_cta():
    payload = build_halt_blocks(make_event(), make_meta(subsector="Diagnostics"))
    assert "triage this name" not in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_no_meta_omit_triage_cta():
    payload = build_halt_blocks(make_event(), None)
    assert "triage this name" not in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_include_note_context_when_provided():
    payload = build_halt_blocks(
        make_event(), make_meta(),
        note_context="Note VRDN is scheduled to report earnings this morning",
    )
    text = payload["blocks"][0]["text"]["text"]
    assert "_Note VRDN is scheduled to report earnings this morning_" in text


def test_halt_blocks_omit_note_context_when_absent():
    payload = build_halt_blocks(make_event(), make_meta())
    text = payload["blocks"][0]["text"]["text"]
    assert "Note " not in text


def test_halt_blocks_include_price():
    payload = build_halt_blocks(make_event(last_price=14.06), make_meta())
    assert "$14.06" in payload["blocks"][0]["text"]["text"]


def test_halt_blocks_handle_missing_price():
    payload = build_halt_blocks(make_event(last_price=None), make_meta())
    assert payload is not None


def test_halt_fallback_no_markdown():
    payload = build_halt_blocks(make_event(), make_meta())
    fallback = payload["text"]
    assert "*" not in fallback
    assert "VRDN" in fallback


def test_resume_blocks():
    event = make_event(resume_trade_time="07:30:00")
    payload = build_resume_blocks(event, make_meta())
    text = payload["blocks"][0]["text"]["text"]
    assert ":white_check_mark:" in text
    assert "07:30 ET" in text
    assert "06:55 ET" in text


def make_news(**overrides):
    defaults = dict(
        source="prnewswire",
        title="Viridian reports positive Phase 3 topline results",
        body="b",
        url="https://prn.test/vrdn",
        published_at="2026-05-05T11:10:00+00:00",  # 07:10 ET
        tickers=("VRDN",),
    )
    defaults.update(overrides)
    return NewsItem(**defaults)


def test_followup_blocks_have_required_fields():
    payload = build_followup_blocks(
        make_event(halt_time="07:00:00"), make_news(), make_meta())
    assert "blocks" in payload
    assert "text" in payload
    assert payload["blocks"][0]["type"] == "section"
    assert payload["blocks"][0]["text"]["type"] == "mrkdwn"


def test_followup_blocks_headline_ticker_and_source():
    payload = build_followup_blocks(
        make_event(halt_time="07:00:00"), make_news(), make_meta())
    text = payload["blocks"][0]["text"]["text"]
    assert ":newspaper:" in text
    assert "*SA:* `VRDN` — Follow-up: Viridian reports positive Phase 3 topline" in text
    assert "07:10 ET 5/05/26" in text
    assert "Follows the 07:00 ET halt on `VRDN`" in text
    assert "PR Newswire press release" in text
    assert "Sector: MedTech / Diagnostics" in text


def test_followup_blocks_include_price():
    payload = build_followup_blocks(make_event(last_price=14.06), make_news(), make_meta())
    assert "$14.06" in payload["blocks"][0]["text"]["text"]


def test_followup_blocks_handle_missing_price():
    payload = build_followup_blocks(make_event(last_price=None), make_news(), make_meta())
    assert "$" not in payload["blocks"][0]["text"]["text"]


def test_followup_blocks_omit_sector_without_meta():
    payload = build_followup_blocks(make_event(), make_news(), None)
    assert "Sector:" not in payload["blocks"][0]["text"]["text"]


def test_followup_fallback_no_markdown():
    payload = build_followup_blocks(make_event(), make_news(), make_meta())
    assert "*" not in payload["text"]
    assert "VRDN" in payload["text"]


@patch("src.slack.requests.post")
def test_post_followup_dry_run_no_post(mock_post):
    payload = post_followup(make_event(), make_news(), make_meta(), dry_run=True)
    mock_post.assert_not_called()
    assert payload is not None


@patch("src.slack.requests.post")
def test_post_followup_live(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status = MagicMock()
    post_followup(make_event(), make_news(), make_meta(), webhook_url="https://test")
    mock_post.assert_called_once()


def test_dm_warning():
    payload = build_dm_blocks("test message")
    assert ":warning:" in payload["blocks"][0]["text"]["text"]


def test_dm_error():
    payload = build_dm_blocks("died", level="error")
    assert ":x:" in payload["blocks"][0]["text"]["text"]


def test_dm_ok():
    payload = build_dm_blocks("ok", level="ok")
    assert ":white_check_mark:" in payload["blocks"][0]["text"]["text"]


def test_resolve_webhook_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_STREET_ACCOUNT", "https://hooks.slack.com/services/TEST")
    assert resolve_webhook_url() == "https://hooks.slack.com/services/TEST"


def test_resolve_webhook_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_STREET_ACCOUNT", "  https://hooks.slack.com/services/TEST\n")
    assert resolve_webhook_url() == "https://hooks.slack.com/services/TEST"


def test_resolve_webhook_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SLACK_WEBHOOK_STREET_ACCOUNT", raising=False)
    f = tmp_path / "webhook.txt"
    f.write_text("https://hooks.slack.com/services/FILE\n")
    assert resolve_webhook_url(file_path=f) == "https://hooks.slack.com/services/FILE"


def test_resolve_webhook_raises_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("SLACK_WEBHOOK_STREET_ACCOUNT", raising=False)
    f = tmp_path / "nonexistent.txt"
    with pytest.raises(SystemExit, match="No Slack webhook"):
        resolve_webhook_url(file_path=f)


@patch("src.slack.requests.post")
def test_post_payload_calls_requests(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status = MagicMock()
    post_payload({"text": "hi"}, webhook_url="https://test")
    mock_post.assert_called_once()


@patch("src.slack.requests.post")
def test_post_halt_dry_run_no_post(mock_post):
    payload = post_halt(make_event(), make_meta(), dry_run=True)
    mock_post.assert_not_called()
    assert payload is not None


@patch("src.slack.requests.post")
def test_post_halt_live(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.raise_for_status = MagicMock()
    post_halt(make_event(), make_meta(), webhook_url="https://test")
    mock_post.assert_called_once()


@patch("src.slack.requests.post")
def test_post_resume_dry_run_no_post(mock_post):
    event = make_event(resume_trade_time="07:30:00")
    payload = post_resume(event, make_meta(), dry_run=True)
    mock_post.assert_not_called()
    assert ":white_check_mark:" in payload["blocks"][0]["text"]["text"]
