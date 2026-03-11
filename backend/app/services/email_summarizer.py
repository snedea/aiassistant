from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.models.source_item import SourceItem
from app.models.email_summary import EmailSummary
from app.services.llm import chat_completion
from app.services.llm_rate_limiter import BudgetExceededError

logger = logging.getLogger(__name__)

_recent_email_summaries: deque[dict[str, Any]] = deque(maxlen=50)


def _build_summarize_prompt(emails: list[dict[str, str]]) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are an email triage assistant. For each email, provide:\n"
            "1. importance: one of \"urgent\", \"important\", \"fyi\", \"ignore\"\n"
            "2. summary: 1-2 sentence summary of the email content\n"
            "\n"
            "Classification rules:\n"
            "- urgent: requires immediate action or response (deadlines today, critical issues, time-sensitive requests)\n"
            "- important: needs attention but not immediate (action items, meeting requests, personal messages from known contacts)\n"
            "- fyi: informational, no action needed (newsletters, updates, receipts, confirmations)\n"
            "- ignore: spam, marketing, bulk mail, automated notifications with no value\n"
            "\n"
            "Respond with a JSON array. Each element must have: \"index\" (int, 0-based position in input), "
            "\"importance\" (string), \"summary\" (string).\n"
            "Return ONLY the JSON array, no other text."
        ),
    }

    parts = []
    for i, email in enumerate(emails):
        body = email.get("body", "")
        parts.append(
            f"Email {i}:\n"
            f"From: {email.get('from_addr', '')}\n"
            f"Subject: {email.get('subject', '')}\n"
            f"Date: {email.get('date', '')}\n"
            f"Body (first 2000 chars): {body[:2000]}\n"
            f"---"
        )

    user_msg = {"role": "user", "content": "\n".join(parts)}
    return [system_msg, user_msg]


def _parse_summary_response(raw_response: str, expected_count: int) -> list[dict[str, Any]]:
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
        logger.warning("Failed to parse LLM summary response as JSON")
        return []

    if not isinstance(parsed, list):
        logger.warning("LLM summary response is not a list")
        return []

    valid_importance = ("urgent", "important", "fyi", "ignore")
    results = []
    for element in parsed:
        try:
            if not isinstance(element, dict):
                continue
            idx = element.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= expected_count:
                continue
            importance = element.get("importance", "fyi")
            if importance not in valid_importance:
                importance = "fyi"
            summary = element.get("summary", "")
            if not isinstance(summary, str):
                summary = ""
            results.append({"index": idx, "importance": importance, "summary": summary})
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed element in LLM summary response")
            continue

    return results


async def summarize_new_emails(session: Session, changed_item_ids: list[int]) -> list[EmailSummary]:
    if not changed_item_ids:
        return []

    stmt = select(SourceItem).where(
        SourceItem.id.in_(changed_item_ids),
        SourceItem.source_type == "email",
    )
    items = list(session.exec(stmt).all())

    if not items:
        return []

    to_summarize = []
    for item in items:
        existing_stmt = select(EmailSummary).where(EmailSummary.external_id == item.external_id)
        existing = session.exec(existing_stmt).first()
        if existing is None:
            to_summarize.append(item)

    if not to_summarize:
        return []

    email_dicts = []
    for item in to_summarize:
        metadata = json.loads(item.raw_metadata)
        email_dicts.append({
            "from_addr": metadata.get("from", ""),
            "subject": item.title,
            "date": metadata.get("date", ""),
            "body": item.content,
        })

    batch_size = 1
    all_summaries: list[EmailSummary] = []
    for batch_start in range(0, len(to_summarize), batch_size):
        batch_items = to_summarize[batch_start:batch_start + batch_size]
        batch_dicts = email_dicts[batch_start:batch_start + batch_size]

        try:
            messages = _build_summarize_prompt(batch_dicts)
            raw_response = await chat_completion(messages, operation="email_triage")
            parsed = _parse_summary_response(raw_response, len(batch_dicts))

            if not parsed:
                logger.warning("Batch starting at %d produced zero parsed results", batch_start)
                continue

            for result in parsed:
                idx = result["index"]
                item = batch_items[idx]
                summary_obj = EmailSummary(
                    source_item_id=item.id,
                    external_id=item.external_id,
                    importance=result["importance"],
                    summary=result["summary"],
                    from_addr=batch_dicts[idx]["from_addr"],
                    subject=item.title,
                )
                session.add(summary_obj)
                all_summaries.append(summary_obj)

                _recent_email_summaries.append({
                    "source_item_id": item.id,
                    "external_id": item.external_id,
                    "importance": result["importance"],
                    "summary": result["summary"],
                    "from": batch_dicts[idx]["from_addr"],
                    "subject": item.title,
                    "summarized_at": datetime.now(timezone.utc).isoformat(),
                })
        except BudgetExceededError:
            raise
        except Exception as e:
            logger.error("Email summarizer batch at %d failed: %s", batch_start, e, exc_info=True)
            continue

    session.commit()

    counts = {"urgent": 0, "important": 0, "fyi": 0, "ignore": 0}
    for s in all_summaries:
        counts[s.importance] = counts.get(s.importance, 0) + 1
    logger.info(
        "Summarized %d new emails: %d urgent, %d important, %d fyi, %d ignore",
        len(all_summaries), counts["urgent"], counts["important"], counts["fyi"], counts["ignore"],
    )

    return all_summaries


def get_recent_summaries() -> list[dict[str, Any]]:
    return list(_recent_email_summaries)


def get_email_summaries(session: Session, importance: str | None = None, limit: int = 50) -> list[EmailSummary]:
    stmt = select(EmailSummary)
    if importance is not None:
        stmt = stmt.where(EmailSummary.importance == importance)
    stmt = stmt.order_by(EmailSummary.created_at.desc()).limit(limit)
    return list(session.exec(stmt).all())
