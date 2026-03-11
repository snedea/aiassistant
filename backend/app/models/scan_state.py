from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class ScanState(SQLModel, table=True):
    __tablename__ = "scan_state"

    id: int | None = Field(default=None, primary_key=True)
    source_type: str = Field(unique=True)
    last_synced_at: datetime | None = Field(default=None)
    last_cursor: str | None = Field(default=None)
    status: str = Field(default="idle")
    error_message: str | None = Field(default=None)
    items_synced: int = Field(default=0)
    last_health_alert_at: datetime | None = Field(default=None)
