from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class NotificationRule(SQLModel, table=True):
    __tablename__ = "notification_rules"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    source_type: str = Field(index=True, unique=True)
    min_priority: str = Field(default="important")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
