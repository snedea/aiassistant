from __future__ import annotations

import json
import logging
import asyncio
import uuid
from datetime import datetime, timedelta, timezone, date, time
from typing import Any

import caldav
from icalendar import Calendar as ICalendar, Event as ICalEvent
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta
from sqlmodel import Session

from app.config import get_settings
from app.services.quiet_hours import get_local_timezone
from app.models.fact import Fact
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)


class ActionResult:
    """Plain data class holding the result of an action command execution."""
    def __init__(self, action_type: str, success: bool, summary: str, details: dict[str, Any]) -> None:
        self.action_type = action_type
        self.success = success
        self.summary = summary
        self.details = details


def _build_action_detection_prompt(user_message: str) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are an action detection engine. Given a user message, determine if it contains a request to:\n"
            '1. Create a reminder or calendar event (e.g., "remind me about X tomorrow", '
            '"schedule a meeting on Friday at 3pm", "add an event for...")\n'
            '2. Remember a fact (e.g., "remember that my dentist is Dr. Smith", '
            '"keep in mind that...")\n\n'
            "Respond with a JSON object with these fields:\n"
            '- "has_action": boolean (true if an action is detected)\n'
            '- "action_type": "create_reminder" | "store_fact" | null\n'
            '- "subject": string (what to remind about, or the fact subject -- 2-5 words)\n'
            '- "content": string (the full reminder text or fact content)\n'
            '- "date_text": string | null (any date/time mentioned, exactly as the user wrote it, '
            'e.g. "tomorrow", "next Tuesday at 3pm", "March 15")\n'
            '- "time_text": string | null (any specific time mentioned, e.g. "3pm", "14:00", '
            '"morning". null if no specific time)\n\n'
            'If "action_type" is "store_fact", set "date_text" and "time_text" to null.\n'
            'If the user says "remind me" but gives no date, set date_text to "tomorrow" as default.\n'
            "Return ONLY the JSON object, no other text."
        ),
    }
    user_msg = {
        "role": "user",
        "content": user_message,
    }
    return [system_msg, user_msg]


def _parse_action_response(raw_response: str) -> dict[str, Any] | None:
    raw_response = raw_response.strip()
    if raw_response.startswith("```"):
        first_newline = raw_response.find("\n")
        if first_newline != -1:
            raw_response = raw_response[first_newline + 1:]
        raw_response = raw_response.rstrip("`").strip()

    try:
        result = json.loads(raw_response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse action detection JSON: %.200s", raw_response)
        return None

    if not isinstance(result, dict):
        return None
    if result.get("has_action") is not True:
        return None
    if result.get("action_type") not in ("create_reminder", "store_fact"):
        return None
    if not result.get("subject"):
        return None
    if not result.get("content"):
        return None
    return result


def _resolve_date(date_text: str | None, time_text: str | None) -> tuple[datetime, datetime]:
    now_utc = datetime.now(timezone.utc)
    local_tz = get_local_timezone()
    now_local = now_utc.astimezone(local_tz)

    if not date_text:
        date_text = "tomorrow"

    date_text_lower = date_text.strip().lower()

    if date_text_lower == "today":
        target_date = now_local.date()
    elif date_text_lower == "tomorrow":
        target_date = now_local.date() + timedelta(days=1)
    elif date_text_lower == "next week":
        target_date = now_local.date() + timedelta(weeks=1)
    else:
        try:
            parsed = dateutil_parser.parse(
                date_text,
                fuzzy=True,
                default=datetime(now_local.year, now_local.month, now_local.day),
            )
            target_date = parsed.date()
            if target_date < now_local.date():
                target_date = target_date.replace(year=target_date.year + 1)
        except ValueError:
            target_date = now_local.date() + timedelta(days=1)

    if time_text is not None and time_text.strip():
        time_text_lower = time_text.strip().lower()
        if time_text_lower == "morning":
            target_time = time(9, 0)
        elif time_text_lower == "afternoon":
            target_time = time(14, 0)
        elif time_text_lower == "evening":
            target_time = time(18, 0)
        elif time_text_lower == "night":
            target_time = time(20, 0)
        else:
            try:
                parsed_time = dateutil_parser.parse(time_text, fuzzy=True)
                target_time = parsed_time.time()
            except ValueError:
                target_time = time(9, 0)
    else:
        target_time = time(9, 0)

    start_local = datetime.combine(target_date, target_time, tzinfo=local_tz)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=1)
    return (start_utc, end_utc)


def _create_caldav_event(summary: str, description: str, start: datetime, end: datetime) -> str | None:
    settings = get_settings()
    if settings.caldav_url == "":
        return None

    client = caldav.DAVClient(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
    )
    principal = client.principal()
    calendars = principal.calendars()
    if len(calendars) == 0:
        logger.warning("No calendars found on CalDAV server")
        return None

    calendar = calendars[0]
    event_uid = str(uuid.uuid4())

    cal = ICalendar()
    cal.add("prodid", "-//AI Assistant//EN")
    cal.add("version", "2.0")
    event = ICalEvent()
    event.add("uid", event_uid)
    event.add("summary", summary)
    event.add("description", description)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.now(timezone.utc))
    cal.add_component(event)
    ical_str = cal.to_ical().decode("utf-8")

    calendar.save_event(ical_str)
    logger.info("Created CalDAV event: %s at %s", summary, start.isoformat())
    return event_uid


def _store_reminder_fact(session: Session, subject: str, content: str, date_text: str | None) -> Fact:
    if date_text is not None and date_text.strip():
        full_content = f"{content} (due: {date_text})"
    else:
        full_content = content

    subject = subject[:100]
    full_content = full_content[:500]

    fact = Fact(
        category="reminder",
        subject=subject,
        content=full_content,
        source_type="action_command",
        source_ref="chat",
        confidence=1.0,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


async def detect_and_execute_action(session: Session, user_message: str) -> ActionResult | None:
    prompt = _build_action_detection_prompt(user_message)
    try:
        raw_response = await chat_completion(prompt, operation="action_detection")
    except Exception:
        logger.warning("Action detection LLM call failed: %s", user_message[:100], exc_info=True)
        return None

    action = _parse_action_response(raw_response)
    if action is None:
        return None

    action_type = action["action_type"]
    subject = str(action["subject"]).strip()
    content = str(action["content"]).strip()
    date_text = action.get("date_text")
    time_text = action.get("time_text")

    if action_type == "create_reminder":
        start_utc, end_utc = _resolve_date(date_text, time_text)

        try:
            event_uid = await asyncio.to_thread(
                _create_caldav_event,
                summary=subject, description=content, start=start_utc, end=end_utc,
            )
        except Exception as exc:
            logger.warning("CalDAV event creation failed, falling back to fact: %s", exc)
            event_uid = None

        if event_uid is not None:
            _store_reminder_fact(session, subject, content, date_text)
            local_tz = get_local_timezone()
            local_start = start_utc.astimezone(local_tz)
            summary_text = f"Created calendar event '{subject}' for {local_start.strftime('%A, %B %d at %I:%M %p')}"
            return ActionResult(
                action_type="calendar_event",
                success=True,
                summary=summary_text,
                details={
                    "event_uid": event_uid,
                    "start": start_utc.isoformat(),
                    "end": end_utc.isoformat(),
                    "subject": subject,
                },
            )
        else:
            fact = _store_reminder_fact(session, subject, content, date_text)
            date_display = date_text if date_text else "tomorrow"
            summary_text = f"Saved reminder '{subject}' for {date_display} (calendar not available, stored as memory fact)"
            return ActionResult(
                action_type="reminder_fact",
                success=True,
                summary=summary_text,
                details={
                    "fact_id": fact.id,
                    "subject": subject,
                    "date_text": date_display,
                },
            )

    if action_type == "store_fact":
        fact = _store_reminder_fact(session, subject, content, None)
        summary_text = f"Remembered: '{subject}' -- {content}"
        return ActionResult(
            action_type="reminder_fact",
            success=True,
            summary=summary_text,
            details={"fact_id": fact.id, "subject": subject},
        )

    return None
