from __future__ import annotations
import uuid
from sqlmodel import Session, select
from app.models.conversation import Conversation


def create_conversation_id() -> str:
    return str(uuid.uuid4())


def add_message(session: Session, conversation_id: str, role: str, content: str) -> Conversation:
    msg = Conversation(conversation_id=conversation_id, role=role, content=content)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def get_history(session: Session, conversation_id: str, limit: int = 50) -> list[Conversation]:
    statement = (
        select(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    rows = list(session.exec(statement).all())
    rows.reverse()
    return rows


def history_to_messages(history: list[Conversation]) -> list[dict[str, str]]:
    return [{"role": msg.role, "content": msg.content} for msg in history]
