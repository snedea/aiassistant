from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.models.source_item import SourceItem
from app.models.item_triage import ItemTriage
from app.services.llm import chat_completion
from app.services.llm_rate_limiter import BudgetExceededError

logger = logging.getLogger(__name__)

_recent_triages: deque[dict[str, Any]] = deque(maxlen=50)

_VALID_PRIORITIES = ("urgent", "important", "fyi", "ignore")


def _build_calendar_triage_prompt(items: list[dict[str, str]]) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are a calendar triage assistant. For each event, provide:\n"
            "1. priority: one of \"urgent\", \"important\", \"fyi\", \"ignore\"\n"
            "2. summary: 1-2 sentence summary of why this event matters\n"
            "\n"
            "Classification rules:\n"
            "- urgent: starts within 1 hour, or contains keywords like \"emergency\", \"ASAP\", \"critical\", \"deadline\"\n"
            "- important: meetings with other people (has attendees), events with action items in description\n"
            "- fyi: recurring routine events, all-day informational events, holidays\n"
            "- ignore: cancelled events (status contains \"CANCELLED\"), tentative with no description\n"
            "\n"
            "Respond with a JSON array. Each element must have: \"index\" (int, 0-based position in input), \"priority\" (string), \"summary\" (string).\n"
            "Return ONLY the JSON array, no other text."
        ),
    }
    parts = []
    for i, item in enumerate(items):
        parts.append(f"Event {i}:")
        parts.append(f"Title: {item['title']}")
        parts.append(f"Start: {item['dtstart']}")
        parts.append(f"End: {item['dtend']}")
        parts.append(f"Location: {item['location']}")
        parts.append(f"Attendees: {item['attendees']}")
        parts.append(f"Status: {item['status']}")
        parts.append(f"Description (first 1000 chars): {item['description'][:1000]}")
        parts.append("---")
    user_msg = {"role": "user", "content": "\n".join(parts)}
    return [system_msg, user_msg]


def _build_notes_triage_prompt(items: list[dict[str, str]]) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are a notes triage assistant. For each note, provide:\n"
            "1. priority: one of \"urgent\", \"important\", \"fyi\", \"ignore\"\n"
            "2. summary: 1-2 sentence summary of the note content and why it matters\n"
            "\n"
            "Classification rules:\n"
            "- urgent: contains deadlines, action items due soon, time-sensitive information\n"
            "- important: contains task lists, project plans, meeting notes with action items, personal reminders\n"
            "- fyi: reference material, general information, bookmarks, recipes, lists without deadlines\n"
            "- ignore: empty or near-empty notes, test notes, random snippets with no context\n"
            "\n"
            "Respond with a JSON array. Each element must have: \"index\" (int, 0-based position in input), \"priority\" (string), \"summary\" (string).\n"
            "Return ONLY the JSON array, no other text."
        ),
    }
    parts = []
    for i, item in enumerate(items):
        parts.append(f"Note {i}:")
        parts.append(f"Title: {item['title']}")
        parts.append(f"Folder: {item['folder']}")
        parts.append(f"Content (first 2000 chars): {item['content'][:2000]}")
        parts.append("---")
    user_msg = {"role": "user", "content": "\n".join(parts)}
    return [system_msg, user_msg]


def _parse_triage_response(raw_response: str, expected_count: int) -> list[dict[str, Any]]:
    raw_response = raw_response.strip()
    if raw_response.startswith("```json"):
        lines = raw_response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_response = "\n".join(lines)
    elif raw_response.startswith("```"):
        lines = raw_response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_response = "\n".join(lines)
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM triage response as JSON")
        return []
    if not isinstance(parsed, list):
        logger.warning("LLM triage response is not a list")
        return []
    results = []
    for element in parsed:
        try:
            if not isinstance(element, dict):
                continue
            idx = element.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= expected_count:
                continue
            priority = element.get("priority", "fyi")
            if priority not in _VALID_PRIORITIES:
                priority = "fyi"
            summary = element.get("summary", "")
            if not isinstance(summary, str):
                summary = ""
            results.append({"index": idx, "priority": priority, "summary": summary})
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed triage element: %s", element)
            continue
    return results


async def triage_items(session: Session, changed_item_ids: list[int], source_type: str) -> list[ItemTriage]:
    if not changed_item_ids:
        return []
    if source_type not in ("calendar", "notes"):
        logger.warning("Triage not supported for source_type: %s", source_type)
        return []
    stmt = select(SourceItem).where(SourceItem.id.in_(changed_item_ids), SourceItem.source_type == source_type)
    items = list(session.exec(stmt).all())
    if not items:
        return []
    to_triage = []
    for item in items:
        existing = session.exec(select(ItemTriage).where(ItemTriage.source_item_id == item.id)).first()
        if existing is None:
            to_triage.append(item)
    if not to_triage:
        return []
    item_dicts = []
    if source_type == "calendar":
        for item in to_triage:
            metadata = json.loads(item.raw_metadata)
            item_dicts.append({
                "title": item.title,
                "dtstart": metadata.get("dtstart", ""),
                "dtend": metadata.get("dtend", ""),
                "location": metadata.get("location", ""),
                "attendees": ", ".join(metadata.get("attendees", [])),
                "status": metadata.get("status", ""),
                "description": item.content,
            })
        prompt_builder = _build_calendar_triage_prompt
    else:
        for item in to_triage:
            metadata = json.loads(item.raw_metadata)
            item_dicts.append({
                "title": item.title,
                "folder": metadata.get("folder", ""),
                "content": item.content,
            })
        prompt_builder = _build_notes_triage_prompt
    batch_size = 1
    all_triages: list[ItemTriage] = []
    for batch_start in range(0, len(to_triage), batch_size):
        batch_items = to_triage[batch_start:batch_start + batch_size]
        batch_dicts = item_dicts[batch_start:batch_start + batch_size]
        try:
            messages = prompt_builder(batch_dicts)
            raw_response = await chat_completion(messages, operation="item_triage")
            parsed = _parse_triage_response(raw_response, len(batch_dicts))
            if not parsed:
                logger.warning("Triage batch at %d produced zero results", batch_start)
                continue
            for result in parsed:
                idx = result["index"]
                item = batch_items[idx]
                triage_obj = ItemTriage(
                    source_item_id=item.id,
                    source_type=source_type,
                    external_id=item.external_id,
                    priority=result["priority"],
                    summary=result["summary"],
                    title=item.title,
                )
                session.add(triage_obj)
                all_triages.append(triage_obj)
                _recent_triages.append({
                    "source_item_id": item.id,
                    "source_type": source_type,
                    "external_id": item.external_id,
                    "priority": result["priority"],
                    "summary": result["summary"],
                    "title": item.title,
                    "triaged_at": datetime.now(timezone.utc).isoformat(),
                })
        except BudgetExceededError:
            raise
        except Exception as e:
            logger.error("Triage batch at %d failed: %s", batch_start, e, exc_info=True)
            continue
    session.commit()
    counts = {"urgent": 0, "important": 0, "fyi": 0, "ignore": 0}
    for t in all_triages:
        counts[t.priority] += 1
    logger.info(
        "Triaged %d %s items: %d urgent, %d important, %d fyi, %d ignore",
        len(all_triages), source_type, counts["urgent"], counts["important"], counts["fyi"], counts["ignore"],
    )
    return all_triages


def get_recent_triages() -> list[dict[str, Any]]:
    return list(_recent_triages)


def get_item_triages(session: Session, source_type: str | None = None, priority: str | None = None, limit: int = 50) -> list[ItemTriage]:
    stmt = select(ItemTriage)
    if source_type is not None:
        stmt = stmt.where(ItemTriage.source_type == source_type)
    if priority is not None:
        stmt = stmt.where(ItemTriage.priority == priority)
    stmt = stmt.order_by(ItemTriage.created_at.desc()).limit(limit)
    return list(session.exec(stmt).all())
