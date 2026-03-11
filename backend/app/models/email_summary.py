from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class EmailSummary(SQLModel, table=True):
    __tablename__ = "email_summaries"

    id: int | None = Field(default=None, primary_key=True)
    source_item_id: int = Field(index=True)
    external_id: str = Field(index=True)
    importance: str = Field(default="fyi")
    summary: str = Field(default="")
    from_addr: str = Field(default="")
    subject: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
