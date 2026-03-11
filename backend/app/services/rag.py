from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session

from app.models.fact import Fact
from app.services.embedding import semantic_search
from app.services.memory import get_facts
from app.services.cross_source import (
    detect_meeting_query,
    find_matching_events,
    gather_related_items,
    format_cross_source_context,
)

logger = logging.getLogger(__name__)


async def retrieve_context(query: str, session: Session, max_sources: int = 6, max_facts: int = 5) -> str:
    try:
        meeting_info = await detect_meeting_query(query)
        if meeting_info is not None:
            events = find_matching_events(
                session,
                meeting_info.get("time_text"),
                meeting_info.get("title_keywords"),
                meeting_info.get("attendee_names"),
            )
            if events:
                related = await gather_related_items(session, events)
                facts = get_facts(session, category=None, active_only=True, limit=max_facts)
                return format_cross_source_context(events, related, facts)

        source_results = await semantic_search(query_text=query, source_type=None, n_results=max_sources)
        source_results = [r for r in source_results if r["score"] >= 0.3]
        facts = get_facts(session, category=None, active_only=True, limit=max_facts)
        if not source_results and not facts:
            return ""
        return _format_context(source_results, facts)
    except Exception as exc:
        logger.warning("RAG retrieval failed: %s", exc, exc_info=True)
        return ""


def _format_context(source_results: list[dict[str, Any]], facts: list[Fact]) -> str:
    parts: list[str] = []
    if source_results:
        parts.append("## Retrieved Information\n")
        for result in source_results:
            source_type = result["metadata"]["source_type"]
            title = result["metadata"]["title"]
            document = result["document"]
            document = document[:1500]
            score = result["score"]
            block = f"### [{source_type.upper()}] {title}\nRelevance: {score:.0%}\n{document}\n"
            parts.append(block)
    if facts:
        parts.append("## Known Facts About User\n")
        for fact in facts:
            parts.append(f"- [{fact.category}] {fact.subject}: {fact.content}")
    return "\n".join(parts)


def build_rag_system_prompt(context: str) -> str:
    base_prompt = "You are a helpful personal AI assistant with access to the user's calendar, notes, and email. Be concise and direct. If you don't know something, say so."
    if not context:
        return base_prompt
    if "## Target Meeting(s)" in context:
        return base_prompt + "\n\nThe user is asking about a specific calendar event. Below is the event information along with related notes and emails found across their data sources. Synthesize this information to give a comprehensive briefing about the meeting. Mention relevant emails, notes, and any preparation needed. Cite the source type when referencing items.\n\n" + context
    return base_prompt + "\n\nBelow is information retrieved from the user's data sources that may be relevant to their question. Use this information to answer accurately. Cite the source type (email, calendar, or notes) when referencing specific items. If the retrieved information doesn't help answer the question, ignore it and respond based on your general knowledge.\n\n" + context
