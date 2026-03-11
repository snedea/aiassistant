from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class Fact(SQLModel, table=True):
    __tablename__ = "facts"

    id: int | None = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    subject: str = Field(index=True)
    content: str
    source_type: str | None = Field(default=None)
    source_ref: str | None = Field(default=None)
    confidence: float = Field(default=1.0)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
