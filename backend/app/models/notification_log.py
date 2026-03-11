from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class NotificationLog(SQLModel, table=True):
    __tablename__ = "notification_log"

    id: int | None = Field(default=None, primary_key=True)
    rule_id: int | None = Field(default=None, index=True)
    source_type: str = Field(index=True)
    external_id: str = Field(index=True)
    channel: str = Field(default="slack")
    priority: str = Field(default="")
    title: str = Field(default="")
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
