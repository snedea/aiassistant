from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: int | None = Field(default=None, primary_key=True)
    role: str = Field(index=True)
    content: str
    conversation_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
