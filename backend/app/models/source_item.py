from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class SourceItem(SQLModel, table=True):
    __tablename__ = "source_items"

    id: int | None = Field(default=None, primary_key=True)
    source_type: str = Field(index=True)
    external_id: str = Field(index=True)
    title: str = Field(default="")
    content: str = Field(default="")
    raw_metadata: str = Field(default="{}")
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = Field(default="")
    embedded: bool = Field(default=False)
    dtstart_utc: datetime | None = Field(default=None, index=True)

    @staticmethod
    def compute_hash(title: str, content: str, raw_metadata: str) -> str:
        combined = f"{title}\n{content}\n{raw_metadata}"
        return hashlib.md5(combined.encode("utf-8")).hexdigest()
