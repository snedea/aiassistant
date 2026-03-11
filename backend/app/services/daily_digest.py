from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select, and_, or_

from app.config import get_settings
from app.database import get_engine
from app.models.source_item import SourceItem
from app.models.email_summary import EmailSummary
from app.models.item_triage import ItemTriage
from app.services.llm import chat_completion
from app.services.quiet_hours import get_local_timezone
from app.notifications.slack import send_slack_webhook
from app.notifications.imessage import send_imessage

logger = logging.getLogger(__name__)


def _get_todays_events(session: Session, local_tz: ZoneInfo) -> list[dict[str, str]]:
    today_local = datetime.now(local_tz).date()
    start_utc = datetime.combine(today_local, time.min, tzinfo=local_tz).astimezone(timezone.utc)
    end_utc = datetime.combine(today_local + timedelta(days=1), time.min, tzinfo=local_tz).astimezone(timezone.utc)
    all_day_marker = today_local.isoformat() + " (all-day)"
    stmt = select(SourceItem).where(
        SourceItem.source_type == "calendar",
        or_(
            and_(
                SourceItem.dtstart_utc.is_not(None),  # type: ignore[union-attr]
                SourceItem.dtstart_utc >= start_utc,  # type: ignore[operator]
                SourceItem.dtstart_utc < end_utc,  # type: ignore[operator]
            ),
            and_(
                SourceItem.dtstart_utc.is_(None),  # type: ignore[union-attr]
                SourceItem.raw_metadata.contains(all_day_marker),  # type: ignore[union-attr]
            ),
        ),
    )
    events = session.exec(stmt).all()
    result: list[dict[str, str]] = []
    for event in events:
        try:
            metadata = json.loads(event.raw_metadata) if event.raw_metadata else {}
            result.append({
                "title": event.title,
                "dtstart": metadata.get("dtstart", ""),
                "dtend": metadata.get("dtend", ""),
                "location": metadata.get("location", ""),
                "attendees": ", ".join(metadata.get("attendees", [])),
            })
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Skipping calendar event %s: %s", getattr(event, 'id', '?'), e)
            continue
    result.sort(key=lambda x: x["dtstart"])
    return result


def _get_pending_emails(session: Session) -> list[dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = (
        select(EmailSummary)
        .where(EmailSummary.created_at >= cutoff, EmailSummary.importance.in_(["urgent", "important"]))
        .order_by(EmailSummary.created_at.desc())
        .limit(20)
    )
    summaries = session.exec(stmt).all()
    return [
        {
            "subject": s.subject,
            "from": s.from_addr,
            "importance": s.importance,
            "summary": s.summary,
        }
        for s in summaries
    ]


def _get_recent_notes(session: Session) -> list[dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = (
        select(ItemTriage)
        .where(ItemTriage.source_type == "notes", ItemTriage.created_at >= cutoff, ItemTriage.priority.in_(["urgent", "important"]))
        .order_by(ItemTriage.created_at.desc())
        .limit(10)
    )
    triages = session.exec(stmt).all()
    return [
        {
            "title": t.title,
            "priority": t.priority,
            "summary": t.summary,
        }
        for t in triages
    ]


def _build_digest_prompt(events: list[dict[str, str]], emails: list[dict[str, str]], notes: list[dict[str, str]], today_str: str) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are a personal assistant generating a morning daily digest. "
            "Summarize the user's day ahead in a concise, friendly briefing. Structure it as:\n"
            "1. Calendar overview (what's on the schedule today)\n"
            "2. Email highlights (urgent/important emails needing attention)\n"
            "3. Notes highlights (recently flagged notes)\n"
            "If a section has no items, say so briefly (e.g., \"No urgent emails.\"). "
            "Keep the total response under 500 words. Use plain text, no markdown. "
            "Do not invent information -- only summarize what is provided."
        ),
    }

    parts = []
    parts.append(f"Daily digest for {today_str}\n")
    parts.append(f"CALENDAR EVENTS TODAY ({len(events)} events):\n")
    if not events:
        parts.append("No events scheduled today.\n")
    else:
        for event in events:
            parts.append(f"- {event['title']} | Start: {event['dtstart']} | Location: {event['location']} | Attendees: {event['attendees']}\n")
    parts.append(f"\nPENDING EMAILS ({len(emails)} items):\n")
    if not emails:
        parts.append("No urgent or important emails.\n")
    else:
        for email in emails:
            parts.append(f"- [{email['importance'].upper()}] From: {email['from']} | Subject: {email['subject']} | Summary: {email['summary']}\n")
    parts.append(f"\nRECENT NOTES ({len(notes)} items):\n")
    if not notes:
        parts.append("No recently flagged notes.\n")
    else:
        for note in notes:
            parts.append(f"- [{note['priority'].upper()}] {note['title']}: {note['summary']}\n")

    user_msg = {"role": "user", "content": "".join(parts)}
    return [system_msg, user_msg]


def _build_digest_slack_blocks(digest_text: str, today_str: str, event_count: int, email_count: int, note_count: int) -> list[dict]:
    header = {"type": "header", "text": {"type": "plain_text", "text": f":sunrise: Daily Digest - {today_str}"}}
    section = {"type": "section", "text": {"type": "mrkdwn", "text": digest_text[:3000]}}
    context = {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{event_count} events | {email_count} emails | {note_count} notes"}]}
    return [header, section, context]


async def generate_and_send_digest() -> bool:
    local_tz = get_local_timezone()
    today_str = datetime.now(local_tz).strftime("%A, %B %d, %Y")
    with Session(get_engine()) as session:
        events = _get_todays_events(session, local_tz)
        emails = _get_pending_emails(session)
        notes = _get_recent_notes(session)
    if not events and not emails and not notes:
        logger.info("Daily digest: nothing to report")
        return False
    messages = _build_digest_prompt(events, emails, notes, today_str)
    digest_text = await chat_completion(messages, operation="daily_digest")
    blocks = _build_digest_slack_blocks(digest_text, today_str, len(events), len(emails), len(notes))
    slack_sent = await send_slack_webhook(text=f"Daily Digest - {today_str}", blocks=blocks)
    await send_imessage(f"Daily Digest - {today_str}\n\n{digest_text}")
    logger.info("Daily digest sent: %d events, %d emails, %d notes", len(events), len(emails), len(notes))
    return slack_sent


async def run_daily_digest_loop() -> None:
    settings = get_settings()
    logger.info("Daily digest loop started (target hour=%d)", settings.digest_hour)
    last_digest_date: date | None = None
    while True:
        local_tz = get_local_timezone()
        now_local = datetime.now(local_tz)
        today = now_local.date()
        if now_local.hour >= settings.digest_hour and last_digest_date != today:
            logger.info("Daily digest: triggering for %s", today.isoformat())
            try:
                await generate_and_send_digest()
            except Exception as e:
                logger.error("Daily digest failed: %s", e, exc_info=True)
            last_digest_date = today
        await asyncio.sleep(60)
