from __future__ import annotations
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class LLMUsage(SQLModel, table=True):
    __tablename__ = "llm_usage"

    id: int | None = Field(default=None, primary_key=True)
    operation: str = Field(index=True)  # "chat", "fact_extraction", "email_triage", "item_triage", "action_detection", "meeting_detection", "daily_digest"
    model: str = Field(default="")
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
