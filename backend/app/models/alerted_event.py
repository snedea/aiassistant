from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class AlertedEvent(SQLModel, table=True):
    __tablename__ = "alerted_events"

    id: int | None = Field(default=None, primary_key=True)
    alert_key: str = Field(unique=True, index=True)  # format: "{external_id}|{dtstart}"
    external_id: str = Field(index=True)
    dtstart: str = Field(default="")
    alerted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
