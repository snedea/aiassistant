from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class ItemTriage(SQLModel, table=True):
    __tablename__ = "item_triages"

    id: int | None = Field(default=None, primary_key=True)
    source_item_id: int = Field(index=True)
    source_type: str = Field(index=True)       # "calendar" or "notes"
    external_id: str = Field(index=True)        # event UID or note ID
    priority: str = Field(default="fyi")        # "urgent", "important", "fyi", "ignore"
    summary: str = Field(default="")            # 1-2 sentence LLM summary
    title: str = Field(default="")              # copied from SourceItem.title for quick access
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
