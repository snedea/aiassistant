from __future__ import annotations
from datetime import datetime, UTC
from sqlmodel import SQLModel, Field


class LLMBudgetConfig(SQLModel, table=True):
    __tablename__ = "llm_budget_config"

    id: int | None = Field(default=None, primary_key=True)
    daily_budget: int = Field(default=500000)
    rate_limit_rpm: int = Field(default=30)
    warning_pct: int = Field(default=80)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
