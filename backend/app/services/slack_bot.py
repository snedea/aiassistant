from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session

from app.config import get_settings
from app.database import get_engine
from app.services.chat_pipeline import run_chat_pipeline

logger = logging.getLogger(__name__)

_handler: Any | None = None


def _is_slack_user_authorized(user_id: str) -> bool:
    settings = get_settings()
    allowed = [u.strip() for u in settings.slack_allowed_user_ids.split(",") if u.strip()]
    if allowed:
        return user_id in allowed
    if settings.api_key:
        return False
    return True


async def start_slack_bot() -> Any | None:
    global _handler
    settings = get_settings()
    if not settings.slack_bot_token or not settings.slack_app_token:
        logger.info("Slack bot not configured (missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN), skipping")
        return None

    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    bolt_app = AsyncApp(token=settings.slack_bot_token)

    @bolt_app.event("message")
    async def handle_message(event: dict[str, Any], say: Any) -> None:
        if event.get("subtype") is not None:
            return
        if event.get("bot_id"):
            return
        if event.get("channel_type") != "im":
            return

        user_id = event.get("user", "")
        if not _is_slack_user_authorized(user_id):
            logger.warning("Unauthorized Slack user %s attempted to use bot", user_id)
            await say(text="Sorry, you are not authorized to use this assistant.", thread_ts=event.get("thread_ts") or event["ts"])
            return

        text = event.get("text", "").strip()
        if not text:
            return

        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        reply_thread_ts = event.get("thread_ts") or event["ts"]
        conversation_id = f"slack:{channel}:{thread_ts}"

        try:
            engine = get_engine()
            with Session(engine) as session:
                result = await run_chat_pipeline(session, text, conversation_id)
            await say(text=result.reply, thread_ts=reply_thread_ts)
        except Exception:
            logger.error("Slack message processing failed", exc_info=True)
            try:
                await say(text="Sorry, I encountered an error processing your message. Please try again.", thread_ts=reply_thread_ts)
            except Exception:
                logger.error("Failed to send error message to Slack", exc_info=True)

    _handler = AsyncSocketModeHandler(bolt_app, settings.slack_app_token)
    await _handler.connect_async()
    logger.info("Slack bot started in Socket Mode")
    return _handler


async def stop_slack_bot() -> None:
    global _handler
    if _handler is not None:
        await _handler.close_async()
        _handler = None
        logger.info("Slack bot stopped")
