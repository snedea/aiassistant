from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from app.services.scanner import start_scanner, stop_scanner, _run_source_sync


@pytest.mark.asyncio
async def test_start_scanner_no_sources_configured() -> None:
    mock_settings = MagicMock()
    mock_settings.caldav_url = ""
    mock_settings.imap_host = ""
    mock_settings.calendar_scan_interval_min = 5
    mock_settings.email_scan_interval_min = 10
    mock_settings.notes_scan_interval_min = 5
    mock_settings.digest_enabled = True
    mock_settings.health_check_interval_min = 5
    with patch("app.services.scanner.get_settings", return_value=mock_settings):
        tasks = await start_scanner()
        assert len(tasks) == 4
        task_names = {t.get_name() for t in tasks}
        assert "scanner-notes" in task_names
        assert "scanner-quiet-hours-flush" in task_names
        assert "scanner-daily-digest" in task_names
        assert "scanner-health-monitor" in task_names
        await stop_scanner(tasks)


@pytest.mark.asyncio
async def test_start_scanner_all_sources() -> None:
    mock_settings = MagicMock()
    mock_settings.caldav_url = "https://example.com"
    mock_settings.imap_host = "imap.example.com"
    mock_settings.calendar_scan_interval_min = 5
    mock_settings.email_scan_interval_min = 10
    mock_settings.notes_scan_interval_min = 30
    mock_settings.digest_enabled = True
    mock_settings.health_check_interval_min = 5
    with patch("app.services.scanner.get_settings", return_value=mock_settings):
        tasks = await start_scanner()
        assert len(tasks) == 7
        task_names = {t.get_name() for t in tasks}
        assert task_names == {"scanner-calendar", "scanner-email", "scanner-notes", "scanner-calendar-alerts", "scanner-quiet-hours-flush", "scanner-daily-digest", "scanner-health-monitor"}
        await stop_scanner(tasks)


@pytest.mark.asyncio
async def test_stop_scanner_cancels_tasks() -> None:
    async def dummy():
        await asyncio.sleep(3600)

    task = asyncio.create_task(dummy(), name="scanner-test")
    await stop_scanner([task])
    assert task.cancelled()


@pytest.mark.asyncio
async def test_run_source_sync_handles_exception() -> None:
    call_count = 0

    def sync_fn(session):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("test error")
        return (1, [])

    mock_engine = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("app.services.scanner.get_engine", return_value=mock_engine), \
         patch("app.services.scanner.Session", return_value=mock_session):
        task = asyncio.create_task(_run_source_sync("test", sync_fn, {}, 0))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert call_count >= 2
