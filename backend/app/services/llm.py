from __future__ import annotations
import logging
import httpx
from app.config import get_settings
from app.services.http_client import get_ollama_client
from app.services.llm_rate_limiter import (
    estimate_messages_tokens,
    estimate_tokens,
    check_rate_limit,
    check_budget,
    log_usage,
    BudgetExceededError,
    RateLimitExceededError,
)

logger = logging.getLogger(__name__)


async def chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    operation: str = "chat",
) -> str:
    settings = get_settings()
    if model is None:
        model = settings.ollama_chat_model

    input_tokens = estimate_messages_tokens(messages)
    check_rate_limit()
    check_budget(input_tokens)

    try:
        client = get_ollama_client()
        response = await client.post(
            "/api/chat",
            json={"model": model, "messages": messages, "stream": False},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Ollama chat failed: %s", e)
        raise

    content = response.json()["message"]["content"].strip()
    output_tokens = estimate_tokens(content)
    log_usage(operation, model, input_tokens, output_tokens)
    return content
