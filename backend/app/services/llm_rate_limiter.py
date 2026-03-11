from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

from sqlmodel import Session, select, func

from app.config import get_settings
from app.database import get_engine
from app.models.llm_usage import LLMUsage
from app.models.llm_budget_config import LLMBudgetConfig

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when the daily LLM token budget has been exhausted."""
    pass


class RateLimitExceededError(Exception):
    """Raised when LLM requests per minute exceeds the configured limit."""
    pass


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(msg["content"]) + 4
    return total


def get_daily_usage(session: Session) -> dict[str, int]:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = session.exec(
        select(func.coalesce(func.sum(LLMUsage.total_tokens), 0), func.count())
        .select_from(LLMUsage)
        .where(LLMUsage.created_at >= today_start)
    ).one()
    total_tokens = result[0]
    call_count = result[1]
    return {"total_tokens": total_tokens, "call_count": call_count}


def get_usage_by_operation(days: int = 1) -> list[dict[str, int | str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with Session(get_engine()) as session:
        rows = session.exec(
            select(
                LLMUsage.operation,
                func.sum(LLMUsage.total_tokens),
                func.sum(LLMUsage.input_tokens),
                func.sum(LLMUsage.output_tokens),
                func.count(),
            )
            .where(LLMUsage.created_at >= cutoff)
            .group_by(LLMUsage.operation)
        ).all()
        return [
            {
                "operation": row[0],
                "total_tokens": row[1],
                "input_tokens": row[2],
                "output_tokens": row[3],
                "call_count": row[4],
            }
            for row in rows
        ]


def log_usage(operation: str, model: str, input_tokens: int, output_tokens: int) -> None:
    try:
        record = LLMUsage(
            operation=operation,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        with Session(get_engine()) as session:
            session.add(record)
            session.commit()
    except Exception:
        logger.warning("Failed to log LLM usage", exc_info=True)


def get_budget_config(session: Session) -> LLMBudgetConfig:
    result = session.exec(select(LLMBudgetConfig)).first()
    if result is not None:
        return result
    settings = get_settings()
    config = LLMBudgetConfig(
        daily_budget=settings.llm_daily_token_budget,
        rate_limit_rpm=settings.llm_rate_limit_rpm,
        warning_pct=settings.llm_budget_warning_pct,
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


_request_timestamps: list[float] = []


def check_rate_limit() -> None:
    with Session(get_engine()) as session:
        config = get_budget_config(session)
    if config.rate_limit_rpm == 0:
        return
    now = time.monotonic()
    _request_timestamps[:] = [ts for ts in _request_timestamps if now - ts < 60.0]
    if len(_request_timestamps) >= config.rate_limit_rpm:
        raise RateLimitExceededError(f"Rate limit exceeded: {config.rate_limit_rpm} requests/min")
    _request_timestamps.append(now)


def check_budget(estimated_input_tokens: int) -> None:
    with Session(get_engine()) as session:
        config = get_budget_config(session)
        if config.daily_budget == 0:
            return
        try:
            usage = get_daily_usage(session)
        except Exception:
            logger.warning("Budget check DB query failed, allowing request", exc_info=True)
            return
        if usage["total_tokens"] + estimated_input_tokens > config.daily_budget:
            raise BudgetExceededError(f"Daily token budget exhausted: {usage['total_tokens']}/{config.daily_budget}")
        if usage["total_tokens"] >= config.daily_budget * config.warning_pct / 100:
            pct = int(usage["total_tokens"] / config.daily_budget * 100)
            logger.warning("LLM budget at %d%% (%d/%d tokens)", pct, usage["total_tokens"], config.daily_budget)


def get_hourly_usage(hours: int = 24) -> list[dict[str, int | str]]:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with Session(get_engine()) as session:
            rows = session.exec(
                select(
                    func.strftime('%Y-%m-%d %H:00', LLMUsage.created_at).label('hour_bucket'),
                    func.sum(LLMUsage.total_tokens),
                    func.count(),
                )
                .where(LLMUsage.created_at >= cutoff)
                .group_by(func.strftime('%Y-%m-%d %H:00', LLMUsage.created_at))
                .order_by(func.strftime('%Y-%m-%d %H:00', LLMUsage.created_at).asc())
            ).all()
            return [
                {"hour": row[0], "total_tokens": row[1], "call_count": row[2]}
                for row in rows
            ]
    except Exception:
        logger.warning("Failed to get hourly usage", exc_info=True)
        return []


def update_budget_settings(daily_budget: int | None = None, rate_limit_rpm: int | None = None, warning_pct: int | None = None) -> dict[str, int]:
    errors: list[str] = []
    if daily_budget is not None and daily_budget < 0:
        errors.append(f"daily_budget must be >= 0 (got {daily_budget})")
    if rate_limit_rpm is not None and rate_limit_rpm < 0:
        errors.append(f"rate_limit_rpm must be >= 0 (got {rate_limit_rpm})")
    if warning_pct is not None:
        if warning_pct < 0:
            errors.append(f"warning_pct must be >= 0 (got {warning_pct})")
        elif warning_pct > 100:
            errors.append(f"warning_pct must be <= 100 (got {warning_pct})")
    if errors:
        raise ValueError("; ".join(errors))
    with Session(get_engine()) as session:
        config = get_budget_config(session)
        if daily_budget is not None:
            config.daily_budget = daily_budget
        if rate_limit_rpm is not None:
            config.rate_limit_rpm = rate_limit_rpm
        if warning_pct is not None:
            config.warning_pct = warning_pct
        config.updated_at = datetime.now(timezone.utc)
        session.add(config)
        session.commit()
        session.refresh(config)
        return {
            "daily_budget": config.daily_budget,
            "rate_limit_rpm": config.rate_limit_rpm,
            "warning_pct": config.warning_pct,
        }


def get_budget_status() -> dict[str, int | float | bool]:
    with Session(get_engine()) as session:
        config = get_budget_config(session)
        try:
            usage = get_daily_usage(session)
        except Exception:
            logger.warning("Budget status DB query failed", exc_info=True)
            return {
                "daily_budget": config.daily_budget,
                "tokens_used": 0,
                "tokens_remaining": -1 if config.daily_budget == 0 else config.daily_budget,
                "pct_used": 0.0,
                "is_exhausted": False,
                "calls_today": 0,
                "rate_limit_rpm": config.rate_limit_rpm,
                "warning_pct": config.warning_pct,
            }
        budget = config.daily_budget
        used = usage["total_tokens"]
        remaining = -1 if budget == 0 else max(0, budget - used)
        pct_used = (used / budget * 100) if budget > 0 else 0.0
        is_exhausted = budget > 0 and used >= budget
        return {
            "daily_budget": budget,
            "tokens_used": used,
            "tokens_remaining": remaining,
            "pct_used": round(pct_used, 1),
            "is_exhausted": is_exhausted,
            "calls_today": usage["call_count"],
            "rate_limit_rpm": config.rate_limit_rpm,
            "warning_pct": config.warning_pct,
        }
