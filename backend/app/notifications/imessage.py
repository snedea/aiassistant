from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def _escape_applescript_string(value: str) -> str:
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    return value


def _build_imessage_text_calendar_alert(alert: dict[str, Any]) -> str:
    title = alert.get("title", "")
    dtstart = alert.get("dtstart", "")
    location = alert.get("location", "")
    msg = f"Upcoming: {title}\nStarts: {dtstart}"
    if location:
        msg += f"\nLocation: {location}"
    return msg


def _build_imessage_text_triage(triage: dict[str, Any]) -> str:
    source_type = triage.get("source_type", "")
    source_label = "Calendar" if source_type == "calendar" else "Note"
    title = triage.get("title", "")
    priority = triage.get("priority", "")
    summary = triage.get("summary", "")
    return f"[{priority.upper()}] {source_label}: {title}\n{summary}"


def _build_imessage_text_email(email_summary: dict[str, Any]) -> str:
    importance = email_summary.get("importance", "")
    subject = email_summary.get("subject", "")
    summary = email_summary.get("summary", "")
    from_addr = email_summary.get("from", "")
    return f"[{importance.upper()}] Email from {from_addr}: {subject}\n{summary}"


async def send_imessage(text: str) -> bool:
    settings = get_settings()
    recipient = settings.imessage_recipient.strip()
    if not recipient:
        logger.debug("iMessage not configured, skipping")
        return False
    try:
        escaped_text = _escape_applescript_string(text)
        escaped_recipient = _escape_applescript_string(recipient)
        script = (
            'tell application "Messages"\n'
            "    set targetService to 1st account whose service type = iMessage\n"
            f'    set targetBuddy to participant "{escaped_recipient}" of targetService\n'
            f'    send "{escaped_text}" to targetBuddy\n'
            "end tell"
        )
        process = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        if process.returncode == 0:
            logger.info("iMessage sent to %s", recipient)
            return True
        else:
            logger.warning("osascript failed (rc=%d): %s", process.returncode, stderr.decode("utf-8"))
            return False
    except TimeoutError:
        logger.error("osascript timed out after 15s, killing process")
        process.kill()
        return False
    except Exception as e:
        logger.error("iMessage send failed: %s", e)
        return False


async def notify_calendar_alert_imessage(alert: dict[str, Any]) -> bool:
    text = _build_imessage_text_calendar_alert(alert)
    return await send_imessage(text)


async def notify_triage_results_imessage(triages: list[dict[str, Any]], min_priority: str = "urgent") -> int:
    priority_rank = {"urgent": 0, "important": 1, "fyi": 2, "ignore": 3}
    min_rank = priority_rank.get(min_priority, 0)
    filtered = [t for t in triages if priority_rank.get(t.get("priority", ""), 3) <= min_rank]
    sent_count = 0
    for triage in filtered:
        text = _build_imessage_text_triage(triage)
        if await send_imessage(text):
            sent_count += 1
    return sent_count


async def notify_email_summaries_imessage(summaries: list[dict[str, Any]], min_importance: str = "urgent") -> int:
    importance_rank = {"urgent": 0, "important": 1, "fyi": 2, "ignore": 3}
    min_rank = importance_rank.get(min_importance, 0)
    filtered = [s for s in summaries if importance_rank.get(s.get("importance", ""), 3) <= min_rank]
    sent_count = 0
    for summary in filtered:
        text = _build_imessage_text_email(summary)
        if await send_imessage(text):
            sent_count += 1
    return sent_count
