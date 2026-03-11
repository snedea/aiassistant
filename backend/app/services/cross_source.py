from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone, time
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select, and_, or_

from app.models.source_item import SourceItem
from app.services.llm import chat_completion
from app.services.embedding import semantic_search
from app.services.quiet_hours import get_local_timezone

logger = logging.getLogger(__name__)


async def detect_meeting_query(user_message: str) -> dict[str, Any] | None:
    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are a query classifier. Determine if the user is asking about "
                "context/preparation for a specific calendar event or meeting. "
                "Respond with ONLY JSON, no other text. "
                'JSON schema: {"is_meeting_query": bool, "time_text": str | null, '
                '"title_keywords": str | null, "attendee_names": list[str] | null}. '
                '"time_text" is the raw time reference (e.g., "3pm", "tomorrow at 2", '
                '"this afternoon"). "title_keywords" is any mentioned meeting name/topic '
                '(e.g., "standup", "budget review"). "attendee_names" is any person names '
                'mentioned (e.g., ["John", "Sarah"]).'
            ),
        }
        user_msg = {"role": "user", "content": user_message}
        raw = await chat_completion([system_msg, user_msg], operation="meeting_detection")

        raw = raw.strip()
        if raw.startswith("```"):
            first_newline = raw.find("\n")
            if first_newline != -1:
                raw = raw[first_newline + 1:]
            raw = raw.rstrip("`").strip()

        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("is_meeting_query") is not True:
            return None
        return result
    except json.JSONDecodeError:
        logger.warning("Failed to parse meeting query detection JSON: %.200s", raw)
        return None
    except Exception as exc:
        logger.warning("Meeting query detection failed: %s", exc, exc_info=True)
        return None


def find_matching_events(
    session: Session,
    time_text: str | None,
    title_keywords: str | None,
    attendee_names: list[str] | None,
) -> list[SourceItem]:
    try:
        local_tz = get_local_timezone()
        now_local = datetime.now(local_tz)
        window_start_local = datetime.combine(
            now_local.date() - timedelta(days=1), time(0, 0), tzinfo=local_tz
        )
        window_end_local = datetime.combine(
            now_local.date() + timedelta(days=3), time(0, 0), tzinfo=local_tz
        )
        window_start_utc = window_start_local.astimezone(timezone.utc)
        window_end_utc = window_end_local.astimezone(timezone.utc)

        all_day_markers = []
        for day_offset in range(-1, 3):
            day = now_local.date() + timedelta(days=day_offset)
            all_day_markers.append(day.isoformat() + " (all-day)")

        all_day_conditions = [
            SourceItem.raw_metadata.contains(marker)  # type: ignore[union-attr]
            for marker in all_day_markers
        ]

        stmt = select(SourceItem).where(
            SourceItem.source_type == "calendar",
            or_(
                and_(
                    SourceItem.dtstart_utc.is_not(None),  # type: ignore[union-attr]
                    SourceItem.dtstart_utc >= window_start_utc,  # type: ignore[operator]
                    SourceItem.dtstart_utc < window_end_utc,  # type: ignore[operator]
                ),
                and_(
                    SourceItem.dtstart_utc.is_(None),  # type: ignore[union-attr]
                    or_(*all_day_conditions),
                ),
            ),
        )
        events = session.exec(stmt).all()

        scored: list[tuple[float, SourceItem]] = []

        for event in events:
            try:
                try:
                    metadata = json.loads(event.raw_metadata)
                except json.JSONDecodeError:
                    continue

                score = 0.0

                if time_text is not None and time_text.strip():
                    dtstart_str = metadata.get("dtstart", "")
                    if dtstart_str and not dtstart_str.endswith("(all-day)"):
                        try:
                            event_dt = datetime.fromisoformat(dtstart_str)
                            local_tz = get_local_timezone()
                            event_local = event_dt.astimezone(local_tz)
                            parsed_time = _parse_time_reference(time_text)
                            if parsed_time is not None:
                                diff_minutes = abs((event_local - parsed_time).total_seconds() / 60)
                                if diff_minutes <= 30:
                                    score += 10.0
                                elif diff_minutes <= 60:
                                    score += 5.0
                                elif diff_minutes <= 120:
                                    score += 2.0
                        except (ValueError, OSError):
                            pass

                if title_keywords is not None and title_keywords.strip():
                    title_lower = event.title.lower()
                    keywords_lower = title_keywords.lower()
                    words = keywords_lower.split()
                    for word in words:
                        if len(word) >= 3 and word in title_lower:
                            score += 3.0

                if attendee_names is not None and len(attendee_names) > 0:
                    attendees_str = json.dumps(metadata.get("attendees", [])).lower()
                    combined = attendees_str + " " + event.title.lower() + " " + event.content.lower()
                    for name in attendee_names:
                        if name.lower() in combined:
                            score += 5.0

                if score > 0:
                    scored.append((score, event))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored and (time_text or title_keywords):
            today_events = []
            for event in events:
                try:
                    metadata = json.loads(event.raw_metadata)
                    dtstart_str = metadata.get("dtstart", "")
                    if dtstart_str and _is_today(dtstart_str):
                        today_events.append(event)
                except (json.JSONDecodeError, ValueError):
                    continue
            return today_events[:3]

        return [item for _, item in scored[:3]]
    except Exception as exc:
        logger.warning("find_matching_events failed: %s", exc, exc_info=True)
        return []


def _parse_time_reference(time_text: str) -> datetime | None:
    from dateutil import parser as dateutil_parser

    local_tz = get_local_timezone()
    now_local = datetime.now(local_tz)
    time_lower = time_text.strip().lower()

    target_date = now_local.date()
    if "tomorrow" in time_lower:
        target_date = now_local.date() + timedelta(days=1)
        time_lower = time_lower.replace("tomorrow", "").strip()
        if not time_lower:
            return datetime.combine(target_date, time(9, 0), tzinfo=local_tz)

    if "morning" in time_lower:
        return datetime.combine(target_date, time(9, 0), tzinfo=local_tz)
    if "afternoon" in time_lower or "after lunch" in time_lower:
        return datetime.combine(target_date, time(13, 0), tzinfo=local_tz)
    if "evening" in time_lower:
        return datetime.combine(target_date, time(17, 0), tzinfo=local_tz)

    try:
        parsed = dateutil_parser.parse(
            time_lower,
            fuzzy=True,
            default=datetime(target_date.year, target_date.month, target_date.day),
        )
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=local_tz)
        return parsed
    except ValueError:
        return None


def _is_today(dtstart_str: str) -> bool:
    try:
        local_tz = get_local_timezone()
        today = datetime.now(local_tz).date()
        if dtstart_str.endswith("(all-day)"):
            d = dtstart_str.replace(" (all-day)", "")
            from datetime import date
            return date.fromisoformat(d) == today
        return datetime.fromisoformat(dtstart_str).astimezone(local_tz).date() == today
    except ValueError:
        return False


def _extract_attendee_name(attendee: str) -> str:
    if "mailto:" in attendee:
        email_part = attendee.split("mailto:")[-1]
        name_part = email_part.split("@")[0]
        return name_part.replace(".", " ")
    return attendee


async def gather_related_items(
    session: Session,
    events: list[SourceItem],
    max_per_source: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    notes_results: list[dict[str, Any]] = []
    emails_results: list[dict[str, Any]] = []

    query_parts: list[str] = []
    attendee_keywords: list[str] = []

    for event in events:
        query_parts.append(event.title)
        if event.content:
            query_parts.append(event.content[:200])
        try:
            metadata = json.loads(event.raw_metadata)
        except json.JSONDecodeError:
            metadata = {}
        attendees = metadata.get("attendees", [])
        if isinstance(attendees, list):
            for att in attendees:
                cleaned = _extract_attendee_name(str(att))
                query_parts.append(cleaned)
                attendee_keywords.append(cleaned)
        location = metadata.get("location", "")
        if location:
            query_parts.append(location)

    composite_query = " ".join(query_parts)
    if not composite_query:
        return {"notes": [], "emails": []}

    try:
        notes_results = await semantic_search(
            query_text=composite_query, source_type="notes", n_results=max_per_source
        )
    except Exception as exc:
        logger.warning("Semantic search for notes failed: %s", exc)

    try:
        emails_results = await semantic_search(
            query_text=composite_query, source_type="email", n_results=max_per_source
        )
    except Exception as exc:
        logger.warning("Semantic search for emails failed: %s", exc)

    notes_results = [r for r in notes_results if r["score"] >= 0.25]
    emails_results = [r for r in emails_results if r["score"] >= 0.25]

    common_words = {"meeting", "sync", "call", "with", "the", "and", "for"}
    title_keywords: list[str] = []
    for event in events:
        words = event.title.lower().split()
        for w in words:
            if len(w) >= 4 and w not in common_words:
                title_keywords.append(w)

    try:
        if attendee_keywords or title_keywords:
            all_keywords = [k.lower() for k in attendee_keywords] + [k.lower() for k in title_keywords]
            recency_cutoff = datetime.now(timezone.utc) - timedelta(days=90)

            keyword_conditions = []
            for kw in all_keywords:
                keyword_conditions.append(func.lower(SourceItem.title).contains(kw))
                keyword_conditions.append(func.lower(SourceItem.content).contains(kw))

            stmt = select(SourceItem).where(
                SourceItem.source_type.in_(["notes", "email"]),
                SourceItem.updated_at >= recency_cutoff,
                or_(*keyword_conditions),
            )
            items = session.exec(stmt).all()

            existing_note_ids = {r["metadata"].get("source_item_id") for r in notes_results}
            existing_email_ids = {r["metadata"].get("source_item_id") for r in emails_results}

            extra_notes = 0
            extra_emails = 0

            for item in items:
                if item.source_type == "notes" and item.id not in existing_note_ids and extra_notes < 3:
                    notes_results.append({
                        "id": f"keyword:{item.id}",
                        "document": item.content,
                        "metadata": {
                            "source_type": item.source_type,
                            "title": item.title,
                            "source_item_id": item.id,
                        },
                        "distance": 1.0,
                        "score": 0.0,
                    })
                    existing_note_ids.add(item.id)
                    extra_notes += 1
                elif item.source_type == "email" and item.id not in existing_email_ids and extra_emails < 3:
                    emails_results.append({
                        "id": f"keyword:{item.id}",
                        "document": item.content,
                        "metadata": {
                            "source_type": item.source_type,
                            "title": item.title,
                            "source_item_id": item.id,
                        },
                        "distance": 1.0,
                        "score": 0.0,
                    })
                    existing_email_ids.add(item.id)
                    extra_emails += 1
    except Exception as exc:
        logger.warning("Keyword matching failed: %s", exc)

    return {"notes": notes_results, "emails": emails_results}


def format_cross_source_context(
    events: list[SourceItem],
    related: dict[str, list[dict[str, Any]]],
    facts: list[Any],
) -> str:
    parts: list[str] = []
    parts.append("## Target Meeting(s)\n")

    for event in events:
        try:
            metadata = json.loads(event.raw_metadata)
        except (json.JSONDecodeError, Exception):
            metadata = {}

        parts.append(f"### {event.title}\n")
        parts.append(f"- Start: {metadata.get('dtstart', 'unknown')}\n")
        parts.append(f"- End: {metadata.get('dtend', 'unknown')}\n")
        location = metadata.get("location", "")
        if location:
            parts.append(f"- Location: {location}\n")
        attendees = metadata.get("attendees", [])
        if isinstance(attendees, list) and attendees:
            parts.append(f"- Attendees: {', '.join(attendees)}\n")
        if event.content:
            parts.append(f"- Description: {event.content[:500]}\n")

    if related.get("notes"):
        parts.append("\n## Related Notes\n")
        for result in related["notes"]:
            title = result["metadata"]["title"]
            doc = result["document"][:1000]
            score = result["score"]
            parts.append(f"### [NOTES] {title}\nRelevance: {score:.0%}\n{doc}\n\n")

    if related.get("emails"):
        parts.append("\n## Related Emails\n")
        for result in related["emails"]:
            title = result["metadata"]["title"]
            doc = result["document"][:1000]
            score = result["score"]
            parts.append(f"### [EMAIL] {title}\nRelevance: {score:.0%}\n{doc}\n\n")

    if facts:
        parts.append("\n## Known Facts About User\n")
        for fact in facts:
            parts.append(f"- [{fact.category}] {fact.subject}: {fact.content}\n")

    return "\n".join(parts)
