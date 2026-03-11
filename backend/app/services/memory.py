from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.fact import Fact
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {"preference", "contact", "deadline", "commitment", "personal", "work", "location", "routine", "reminder"}


def _build_extraction_prompt(user_message: str, assistant_reply: str) -> list[dict[str, str]]:
    system_msg = {
        "role": "system",
        "content": (
            "You are a fact extraction engine. Given a conversation between a user and an assistant, "
            "extract any personal facts about the user. Return a JSON array of objects with these fields: "
            '"category" (one of: "preference", "contact", "deadline", "commitment", "personal", "work", '
            '"location", "routine"), "subject" (short label, 2-5 words), "content" (the fact as a complete '
            "sentence). Only extract facts that are explicitly stated or strongly implied. If no facts can "
            "be extracted, return an empty array: []. Return ONLY the JSON array, no other text."
        ),
    }
    user_msg = {
        "role": "user",
        "content": f"User: {user_message}\n\nAssistant: {assistant_reply}",
    }
    return [system_msg, user_msg]


def _clean_extracted_facts(raw_response: str) -> list[dict[str, str]]:
    raw_response = raw_response.strip()
    if raw_response.startswith("```"):
        first_newline = raw_response.find("\n")
        if first_newline != -1:
            raw_response = raw_response[first_newline + 1:]
        raw_response = raw_response.rstrip("`").strip()

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse fact extraction JSON: %.200s", raw_response)
        return []

    if not isinstance(parsed, list):
        return []

    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not all(k in item for k in ("category", "subject", "content")):
            continue
        category = str(item["category"]).strip()
        subject = str(item["subject"]).strip()
        content = str(item["content"]).strip()
        if category not in ALLOWED_CATEGORIES:
            continue
        subject = subject[:100]
        content = content[:500]
        result.append({"category": category, "subject": subject, "content": content})

    return result


async def extract_and_store_facts(
    session: Session, user_message: str, assistant_reply: str, conversation_id: str
) -> list[Fact]:
    messages = _build_extraction_prompt(user_message, assistant_reply)
    raw_response = await chat_completion(messages, operation="fact_extraction")
    fact_dicts = _clean_extracted_facts(raw_response)
    if not fact_dicts:
        return []

    stored_facts: list[Fact] = []
    for fact_dict in fact_dicts:
        statement = select(Fact).where(
            Fact.subject == fact_dict["subject"],
            Fact.category == fact_dict["category"],
            Fact.active == True,  # noqa: E712
        )
        existing = session.exec(statement).first()
        if existing:
            existing.content = fact_dict["content"]
            existing.updated_at = datetime.now(timezone.utc)
            existing.source_type = "conversation"
            existing.source_ref = conversation_id
            session.add(existing)
            stored_facts.append(existing)
        else:
            new_fact = Fact(
                category=fact_dict["category"],
                subject=fact_dict["subject"],
                content=fact_dict["content"],
                source_type="conversation",
                source_ref=conversation_id,
                confidence=0.9,
            )
            session.add(new_fact)
            stored_facts.append(new_fact)

    session.commit()
    for fact in stored_facts:
        session.refresh(fact)

    logger.info("Extracted %d facts from conversation %s", len(stored_facts), conversation_id)
    return stored_facts


def get_facts(session: Session, category: str | None = None, active_only: bool = True, limit: int | None = None) -> list[Fact]:
    statement = select(Fact)
    if active_only:
        statement = statement.where(Fact.active == True)  # noqa: E712
    if category is not None:
        statement = statement.where(Fact.category == category)
    statement = statement.order_by(Fact.updated_at.desc())
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())


def deactivate_fact(session: Session, fact_id: int) -> Fact | None:
    fact = session.get(Fact, fact_id)
    if fact is None:
        return None
    fact.active = False
    fact.updated_at = datetime.now(timezone.utc)
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact
