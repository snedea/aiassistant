from __future__ import annotations
from datetime import datetime, UTC
from sqlmodel import SQLModel, Field


class QuietHoursConfig(SQLModel, table=True):
    __tablename__ = "quiet_hours_config"

    id: int | None = Field(default=None, primary_key=True)
    start_time: str = Field(default="22:00")  # 24h format HH:MM
    end_time: str = Field(default="07:00")    # 24h format HH:MM
    timezone: str = Field(default="America/Chicago")
    enabled: bool = Field(default=False)
    bypass_urgent: bool = Field(default=True)  # urgent notifications ignore quiet hours
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
