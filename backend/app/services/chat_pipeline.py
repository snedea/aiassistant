from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlmodel import Session

from app.services.llm import chat_completion
from app.services.llm_rate_limiter import BudgetExceededError, RateLimitExceededError
from app.services.conversation import add_message, get_history, history_to_messages
from app.services.memory import extract_and_store_facts
from app.services.rag import retrieve_context, build_rag_system_prompt
from app.services.action_commands import detect_and_execute_action, ActionResult
from app.database import get_engine

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    reply: str
    action_result: ActionResult | None


async def run_chat_pipeline(session: Session, message: str, conversation_id: str) -> PipelineResult:
    add_message(session, conversation_id, "user", message)

    action_result = None
    try:
        action_result = await detect_and_execute_action(session, message)
    except Exception:
        logger.warning("Action detection failed for conversation %s", conversation_id, exc_info=True)

    history = get_history(session, conversation_id, limit=50)
    context = await retrieve_context(message, session)
    system_prompt = build_rag_system_prompt(context)

    if action_result is not None and action_result.success:
        system_prompt += (
            "\n\n## Action Executed\n"
            "The following action was automatically performed based on the user's message:\n"
            "- " + action_result.summary + "\n"
            "Acknowledge this action in your reply. Confirm what was done and provide the details."
        )

    messages = history_to_messages(history)
    messages.insert(0, {"role": "system", "content": system_prompt})

    try:
        reply = await chat_completion(messages, operation="chat")
    except BudgetExceededError:
        reply = "I've reached my daily processing limit. I'll be available again tomorrow. You can check usage details in the admin dashboard."
    except RateLimitExceededError:
        reply = "I'm receiving too many requests right now. Please wait a moment and try again."

    add_message(session, conversation_id, "assistant", reply)

    asyncio.create_task(_extract_facts_background(message, reply, conversation_id))

    return PipelineResult(reply=reply, action_result=action_result)


async def _extract_facts_background(user_msg: str, assistant_msg: str, conv_id: str) -> None:
    try:
        engine = get_engine()
        with Session(engine) as bg_session:
            await extract_and_store_facts(bg_session, user_msg, assistant_msg, conv_id)
    except Exception:
        logger.warning("Fact extraction failed for conversation %s", conv_id, exc_info=True)
