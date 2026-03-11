from __future__ import annotations
from datetime import datetime, UTC
from sqlmodel import SQLModel, Field


class HeldNotification(SQLModel, table=True):
    __tablename__ = "held_notifications"

    id: int | None = Field(default=None, primary_key=True)
    source_type: str = Field(index=True)
    external_id: str = Field(index=True)
    priority: str = Field(default="")
    title: str = Field(default="")
    channel: str = Field(default="slack")
    payload_json: str = Field(default="{}")  # JSON-serialized notification payload
    notification_type: str = Field(default="triage")  # "triage", "email", "calendar_alert"
    rule_id: int | None = Field(default=None)
    flush_attempts: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
