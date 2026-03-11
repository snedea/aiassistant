from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import httpx
import pytest

from app.services.slack_bot import _is_slack_user_authorized
from app.notifications.slack import (
    send_slack_webhook,
    notify_calendar_alert,
    notify_triage_results,
    notify_email_summaries,
    _priority_emoji,
    _truncate_header,
    _build_calendar_alert_blocks,
    _build_triage_blocks,
    _build_email_summary_blocks,
)


def test_priority_emoji_mapping() -> None:
    assert _priority_emoji("urgent") == ":red_circle:"
    assert _priority_emoji("important") == ":large_orange_circle:"
    assert _priority_emoji("fyi") == ":large_blue_circle:"
    assert _priority_emoji("ignore") == ":white_circle:"
    assert _priority_emoji("unknown") == ":white_circle:"


def test_truncate_header_short() -> None:
    assert _truncate_header("Hello") == "Hello"
    assert _truncate_header("x" * 150) == "x" * 150


def test_truncate_header_long() -> None:
    long_text = "A" * 200
    result = _truncate_header(long_text)
    assert len(result) == 150
    assert result.endswith("...")
    assert result == "A" * 147 + "..."


def test_build_calendar_alert_blocks() -> None:
    alert = {
        "title": "Team Standup",
        "dtstart": "2026-03-10T10:00:00Z",
        "dtend": "2026-03-10T10:30:00Z",
        "location": "Zoom",
        "event_id": 1,
        "external_id": "abc123",
        "alerted_at": "2026-03-10T09:50:00Z",
    }
    blocks = _build_calendar_alert_blocks(alert)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "header"
    assert "Team Standup" in blocks[0]["text"]["text"]
    assert blocks[1]["type"] == "section"
    assert "Zoom" in blocks[1]["text"]["text"]


def test_build_calendar_alert_blocks_long_title() -> None:
    alert = {"title": "A" * 200, "dtstart": "2026-03-10T10:00:00Z", "location": ""}
    blocks = _build_calendar_alert_blocks(alert)
    assert len(blocks[0]["text"]["text"]) <= 150
    assert blocks[0]["text"]["text"].endswith("...")


def test_build_triage_blocks() -> None:
    triage = {
        "source_type": "calendar",
        "title": "Budget Review",
        "priority": "urgent",
        "summary": "Critical budget deadline",
    }
    blocks = _build_triage_blocks(triage)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "header"
    assert "Budget Review" in blocks[0]["text"]["text"]
    assert ":red_circle:" in blocks[0]["text"]["text"]


def test_build_triage_blocks_long_title() -> None:
    triage = {"source_type": "calendar", "title": "B" * 200, "priority": "important", "summary": "test"}
    blocks = _build_triage_blocks(triage)
    assert len(blocks[0]["text"]["text"]) <= 150
    assert blocks[0]["text"]["text"].endswith("...")


def test_build_email_summary_blocks() -> None:
    summary = {
        "importance": "important",
        "subject": "Q1 Report",
        "summary": "Quarterly results attached",
        "from": "boss@company.com",
    }
    blocks = _build_email_summary_blocks(summary)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "header"
    assert "Q1 Report" in blocks[0]["text"]["text"]


def test_build_email_summary_blocks_long_subject() -> None:
    summary = {"importance": "important", "subject": "C" * 200, "summary": "test", "from": "x@y.com"}
    blocks = _build_email_summary_blocks(summary)
    assert len(blocks[0]["text"]["text"]) <= 150
    assert blocks[0]["text"]["text"].endswith("...")


@pytest.mark.asyncio
async def test_send_slack_webhook_not_configured() -> None:
    mock_settings = MagicMock(slack_webhook_url="")
    with patch("app.notifications.slack.get_settings", return_value=mock_settings):
        result = await send_slack_webhook("test message")
    assert result is False


@pytest.mark.asyncio
async def test_send_slack_webhook_success() -> None:
    mock_settings = MagicMock(slack_webhook_url="https://hooks.slack.com/test")
    mock_response = MagicMock(status_code=200, text="ok")
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.notifications.slack.get_settings", return_value=mock_settings), \
         patch("app.notifications.slack.get_slack_client", return_value=mock_client):
        result = await send_slack_webhook(
            "test message",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}],
        )

    assert result is True
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "json" in call_kwargs.kwargs or len(call_kwargs.args) >= 2
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "text" in payload
    assert "blocks" in payload


@pytest.mark.asyncio
async def test_send_slack_webhook_failure() -> None:
    mock_settings = MagicMock(slack_webhook_url="https://hooks.slack.com/test")
    mock_response = MagicMock(status_code=403, text="invalid_token")
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.notifications.slack.get_settings", return_value=mock_settings), \
         patch("app.notifications.slack.get_slack_client", return_value=mock_client):
        result = await send_slack_webhook("test")

    assert result is False


@pytest.mark.asyncio
async def test_send_slack_webhook_http_error() -> None:
    mock_settings = MagicMock(slack_webhook_url="https://hooks.slack.com/test")
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("app.notifications.slack.get_settings", return_value=mock_settings), \
         patch("app.notifications.slack.get_slack_client", return_value=mock_client):
        result = await send_slack_webhook("test")

    assert result is False


@pytest.mark.asyncio
async def test_notify_triage_results_filters_by_priority() -> None:
    triages = [
        {"source_type": "calendar", "title": "Urgent Meeting", "priority": "urgent", "summary": "Now"},
        {"source_type": "calendar", "title": "Important Review", "priority": "important", "summary": "Soon"},
        {"source_type": "notes", "title": "FYI Note", "priority": "fyi", "summary": "Later"},
    ]
    with patch("app.notifications.slack.send_slack_webhook", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_triage_results(triages, min_priority="urgent")
        assert result == 1
        assert mock_send.call_count == 1

        mock_send.reset_mock()
        result = await notify_triage_results(triages, min_priority="important")
        assert result == 2


@pytest.mark.asyncio
async def test_notify_email_summaries_filters_by_importance() -> None:
    summaries = [
        {"importance": "urgent", "subject": "Server Down", "summary": "Outage", "from": "ops@co.com"},
        {"importance": "fyi", "subject": "Newsletter", "summary": "Weekly update", "from": "news@co.com"},
    ]
    with patch("app.notifications.slack.send_slack_webhook", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_email_summaries(summaries, min_importance="urgent")
        assert result == 1
        assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_notify_calendar_alert() -> None:
    alert = {
        "title": "Team Standup",
        "dtstart": "2026-03-10T10:00:00Z",
        "dtend": "2026-03-10T10:30:00Z",
        "location": "Zoom",
    }
    with patch("app.notifications.slack.send_slack_webhook", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_calendar_alert(alert)
        assert result is True
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert "text" in call_kwargs
        assert "blocks" in call_kwargs


def test_slack_user_authorized_dev_mode(monkeypatch) -> None:
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "")
    get_settings.cache_clear()
    assert _is_slack_user_authorized("U_ANYONE") is True
    get_settings.cache_clear()


def test_slack_user_denied_when_auth_enabled_no_allowlist(monkeypatch) -> None:
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "secret-key-123")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "")
    get_settings.cache_clear()
    assert _is_slack_user_authorized("U_ANYONE") is False
    get_settings.cache_clear()


def test_slack_user_allowed_in_allowlist(monkeypatch) -> None:
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "secret-key-123")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U01ABC123, U04DEF456")
    get_settings.cache_clear()
    assert _is_slack_user_authorized("U01ABC123") is True
    assert _is_slack_user_authorized("U04DEF456") is True
    get_settings.cache_clear()


def test_slack_user_denied_not_in_allowlist(monkeypatch) -> None:
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "secret-key-123")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U01ABC123")
    get_settings.cache_clear()
    assert _is_slack_user_authorized("U_INTRUDER") is False
    get_settings.cache_clear()


def test_slack_allowlist_overrides_dev_mode(monkeypatch) -> None:
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U01ABC123")
    get_settings.cache_clear()
    assert _is_slack_user_authorized("U01ABC123") is True
    assert _is_slack_user_authorized("U_OTHER") is False
    get_settings.cache_clear()
