from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from app.services.http_client import get_slack_client

from app.config import get_settings

logger = logging.getLogger(__name__)

_PRIORITY_EMOJIS = {
    "urgent": ":red_circle:",
    "important": ":large_orange_circle:",
    "fyi": ":large_blue_circle:",
    "ignore": ":white_circle:",
}


def _priority_emoji(priority: str) -> str:
    return _PRIORITY_EMOJIS.get(priority, ":white_circle:")


def _truncate_header(text: str, max_len: int = 150) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _build_calendar_alert_blocks(alert: dict[str, Any]) -> list[dict[str, Any]]:
    title = alert.get("title", "")
    dtstart = alert.get("dtstart", "")
    location = alert.get("location", "")

    try:
        dt = datetime.fromisoformat(dtstart if dtstart.endswith("Z") or "+" in dtstart or dtstart.endswith("]") else dtstart + "Z")
        formatted_start = dt.strftime("%a %b %d, %I:%M %p")
    except ValueError:
        formatted_start = dtstart

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _truncate_header(f":calendar: Upcoming: {title}")},
        },
    ]

    section_lines = [f"*Starts:* {formatted_start}"]
    if location:
        section_lines.append(f"*Location:* {location}")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(section_lines)},
    })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Event alert from AI Assistant"}],
    })

    return blocks


def _build_triage_blocks(triage: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = triage.get("source_type", "")
    title = triage.get("title", "")
    priority = triage.get("priority", "")
    summary = triage.get("summary", "")

    emoji = _priority_emoji(priority)
    source_label = "Calendar" if source_type == "calendar" else "Note"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _truncate_header(f"{emoji} {source_label}: {title}")},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Priority:* {priority}\n*Summary:* {summary}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Triaged by AI Assistant"}],
        },
    ]


def _build_email_summary_blocks(email_summary: dict[str, Any]) -> list[dict[str, Any]]:
    importance = email_summary.get("importance", "")
    subject = email_summary.get("subject", "")
    summary = email_summary.get("summary", "")
    from_addr = email_summary.get("from", "")

    emoji = _priority_emoji(importance)

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _truncate_header(f"{emoji} Email: {subject}")},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*From:* {from_addr}\n*Importance:* {importance}\n*Summary:* {summary}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Summarized by AI Assistant"}],
        },
    ]


async def send_slack_webhook(text: str, blocks: list[dict[str, Any]] | None = None) -> bool:
    settings = get_settings()
    if not settings.slack_webhook_url:
        logger.debug("Slack webhook not configured, skipping")
        return False

    payload: dict[str, Any] = {"text": text}
    if blocks is not None:
        payload["blocks"] = blocks

    try:
        client = get_slack_client()
        response = await client.post(settings.slack_webhook_url, json=payload)
        if response.status_code == 200:
            logger.info("Slack notification sent")
            return True
        logger.warning("Slack webhook returned status %d: %s", response.status_code, response.text)
        return False
    except httpx.HTTPError as e:
        logger.error("Slack webhook request failed: %s", e)
        return False
    except Exception as e:
        logger.error("Slack webhook request failed: %s", e)
        return False


async def notify_calendar_alert(alert: dict[str, Any]) -> bool:
    blocks = _build_calendar_alert_blocks(alert)
    fallback_text = f"Upcoming event: {alert.get('title', '')}"
    return await send_slack_webhook(text=fallback_text, blocks=blocks)


async def notify_triage_results(triages: list[dict[str, Any]], min_priority: str = "urgent") -> int:
    priority_rank = {"urgent": 0, "important": 1, "fyi": 2, "ignore": 3}
    min_rank = priority_rank.get(min_priority, 0)
    filtered = [t for t in triages if priority_rank.get(t.get("priority", ""), 3) <= min_rank]

    sent_count = 0
    for triage in filtered:
        blocks = _build_triage_blocks(triage)
        fallback_text = f"{triage.get('source_type', '')} [{triage.get('priority', '')}]: {triage.get('title', '')}"
        result = await send_slack_webhook(text=fallback_text, blocks=blocks)
        if result:
            sent_count += 1
    return sent_count


async def notify_email_summaries(summaries: list[dict[str, Any]], min_importance: str = "urgent") -> int:
    importance_rank = {"urgent": 0, "important": 1, "fyi": 2, "ignore": 3}
    min_rank = importance_rank.get(min_importance, 0)
    filtered = [s for s in summaries if importance_rank.get(s.get("importance", ""), 3) <= min_rank]

    sent_count = 0
    for summary in filtered:
        blocks = _build_email_summary_blocks(summary)
        fallback_text = f"Email [{summary.get('importance', '')}]: {summary.get('subject', '')}"
        result = await send_slack_webhook(text=fallback_text, blocks=blocks)
        if result:
            sent_count += 1
    return sent_count
