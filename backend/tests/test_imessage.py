from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.notifications.imessage import (
    send_imessage,
    notify_calendar_alert_imessage,
    notify_triage_results_imessage,
    notify_email_summaries_imessage,
    _escape_applescript_string,
    _build_imessage_text_calendar_alert,
    _build_imessage_text_triage,
    _build_imessage_text_email,
)


def test_escape_applescript_string_no_special_chars() -> None:
    assert _escape_applescript_string("hello world") == "hello world"


def test_escape_applescript_string_with_quotes() -> None:
    assert _escape_applescript_string('say "hi"') == 'say \\"hi\\"'


def test_escape_applescript_string_with_backslash() -> None:
    assert _escape_applescript_string("path\\to\\file") == "path\\\\to\\\\file"


def test_build_imessage_text_calendar_alert() -> None:
    alert = {"title": "Team Standup", "dtstart": "2026-03-10T10:00:00Z", "location": "Zoom"}
    result = _build_imessage_text_calendar_alert(alert)
    assert "Upcoming: Team Standup" in result
    assert "Starts: 2026-03-10T10:00:00Z" in result
    assert "Location: Zoom" in result


def test_build_imessage_text_calendar_alert_no_location() -> None:
    alert = {"title": "Lunch", "dtstart": "2026-03-10T12:00:00Z"}
    result = _build_imessage_text_calendar_alert(alert)
    assert "Upcoming: Lunch" in result
    assert "Location" not in result


def test_build_imessage_text_triage() -> None:
    triage = {"source_type": "calendar", "title": "Budget Review", "priority": "urgent", "summary": "Critical deadline"}
    result = _build_imessage_text_triage(triage)
    assert "[URGENT]" in result
    assert "Calendar: Budget Review" in result
    assert "Critical deadline" in result


def test_build_imessage_text_email() -> None:
    summary = {"importance": "important", "subject": "Q1 Report", "summary": "Results attached", "from": "boss@co.com"}
    result = _build_imessage_text_email(summary)
    assert "[IMPORTANT]" in result
    assert "boss@co.com" in result
    assert "Q1 Report" in result


@pytest.mark.asyncio
async def test_send_imessage_not_configured() -> None:
    mock_settings = MagicMock(imessage_recipient="")
    with patch("app.notifications.imessage.get_settings", return_value=mock_settings):
        result = await send_imessage("test")
    assert result is False


@pytest.mark.asyncio
async def test_send_imessage_success() -> None:
    mock_settings = MagicMock(imessage_recipient="+15551234567")
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    with patch("app.notifications.imessage.get_settings", return_value=mock_settings), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await send_imessage("hello")
    assert result is True
    assert mock_exec.call_args[0][0] == "osascript"


@pytest.mark.asyncio
async def test_send_imessage_osascript_failure() -> None:
    mock_settings = MagicMock(imessage_recipient="+15551234567")
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate = AsyncMock(return_value=(b"", b"error message"))
    with patch("app.notifications.imessage.get_settings", return_value=mock_settings), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await send_imessage("hello")
    assert result is False


@pytest.mark.asyncio
async def test_notify_triage_results_imessage_filters_by_priority() -> None:
    triages = [
        {"source_type": "calendar", "title": "A", "priority": "urgent", "summary": "s1"},
        {"source_type": "calendar", "title": "B", "priority": "important", "summary": "s2"},
        {"source_type": "notes", "title": "C", "priority": "fyi", "summary": "s3"},
    ]
    with patch("app.notifications.imessage.send_imessage", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_triage_results_imessage(triages, min_priority="urgent")
    assert result == 1
    assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_notify_email_summaries_imessage_filters_by_importance() -> None:
    summaries = [
        {"importance": "urgent", "subject": "A", "summary": "s1", "from": "a@b.com"},
        {"importance": "fyi", "subject": "B", "summary": "s2", "from": "c@d.com"},
    ]
    with patch("app.notifications.imessage.send_imessage", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_email_summaries_imessage(summaries, min_importance="urgent")
    assert result == 1
    assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_notify_calendar_alert_imessage() -> None:
    alert = {"title": "Meeting", "dtstart": "2026-03-10T14:00:00Z"}
    with patch("app.notifications.imessage.send_imessage", new_callable=AsyncMock, return_value=True) as mock_send:
        result = await notify_calendar_alert_imessage(alert)
    assert result is True
    assert mock_send.call_count == 1
    assert "Meeting" in mock_send.call_args[0][0]
