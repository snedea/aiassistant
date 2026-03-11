from __future__ import annotations

import logging

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.database import get_session
from app.auth import require_auth
from app.services.conversation import create_conversation_id, get_history
from app.services.chat_pipeline import run_chat_pipeline

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ActionInfo(BaseModel):
    action_type: str
    success: bool
    summary: str

class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    action: ActionInfo | None = None


router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_auth)])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    if request.conversation_id is None:
        conversation_id = create_conversation_id()
    else:
        conversation_id = request.conversation_id

    try:
        result = await run_chat_pipeline(session, request.message, conversation_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM service unavailable: {e}")

    action_info: ActionInfo | None = None
    if result.action_result is not None:
        action_info = ActionInfo(
            action_type=result.action_result.action_type,
            success=result.action_result.success,
            summary=result.action_result.summary,
        )

    return ChatResponse(conversation_id=conversation_id, reply=result.reply, action=action_info)


@router.get("/history/{conversation_id}")
async def get_chat_history(conversation_id: str, session: Session = Depends(get_session)) -> dict:
    history = get_history(session, conversation_id, limit=100)
    return {
        "conversation_id": conversation_id,
        "messages": [
            {"role": msg.role, "content": msg.content, "created_at": msg.created_at.isoformat()}
            for msg in history
        ],
    }
