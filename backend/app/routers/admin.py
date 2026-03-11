from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import require_auth
from app.database import get_session
from app.services.admin import (
    reindex_vectorstore,
    clear_facts,
    clear_conversations,
    clear_source_items,
    test_all_connections,
    test_connection_ollama,
    test_connection_caldav,
    test_connection_imap,
    test_connection_notes,
    test_connection_slack,
)
from app.adapters.calendar import sync_calendar_events
from app.adapters.notes import sync_notes
from app.adapters.email import sync_emails
from app.services.embedding import embed_source_items
from app.models.source_item import SourceItem
from app.services.vectorstore import collection_count
from app.services.llm_rate_limiter import get_budget_status, get_usage_by_operation, get_daily_usage, get_hourly_usage, update_budget_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_auth)])


class ClearMemoryRequest(BaseModel):
    scope: str
    category: str | None = None
    source_type: str | None = None


class UpdateBudgetRequest(BaseModel):
    daily_budget: int | None = None
    rate_limit_rpm: int | None = None
    warning_pct: int | None = None


@router.post("/reindex")
async def admin_reindex(session: Session = Depends(get_session)) -> dict:
    try:
        result = await reindex_vectorstore(session)
        return {"status": "ok", "old_count": result["old_count"], "new_count": result["new_count"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)[:200]}")


@router.post("/memory/clear")
async def admin_clear_memory(body: ClearMemoryRequest, session: Session = Depends(get_session)) -> dict:
    if body.scope not in {"facts", "conversations", "source_items", "all"}:
        raise HTTPException(status_code=400, detail="scope must be one of: facts, conversations, source_items, all")
    result = {}
    if body.scope in ("facts", "all"):
        result["facts_cleared"] = clear_facts(session, category=body.category)
    if body.scope in ("conversations", "all"):
        result["conversations_cleared"] = clear_conversations(session)
    if body.scope in ("source_items", "all"):
        result["source_items_cleared"] = clear_source_items(session, source_type=body.source_type)
    return {"status": "ok", **result}


@router.get("/connections")
async def admin_connections() -> dict:
    results = await test_all_connections()
    return {"connections": results, "count": len(results)}


@router.post("/connections/{source}/test")
async def admin_test_connection(source: str) -> dict:
    test_fns = {
        "ollama": test_connection_ollama,
        "caldav": test_connection_caldav,
        "imap": test_connection_imap,
        "notes": test_connection_notes,
        "slack": test_connection_slack,
    }
    if source not in test_fns:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}. Must be one of: {', '.join(test_fns.keys())}")
    result = await test_fns[source]()
    return {"connection": result}


@router.get("/stats")
async def admin_stats(session: Session = Depends(get_session)) -> dict:
    from sqlmodel import select, func
    from app.models.fact import Fact
    from app.models.conversation import Conversation
    from app.models.source_item import SourceItem

    facts_count = session.exec(select(func.count()).select_from(Fact).where(Fact.active == True)).one()
    conversations_count = session.exec(select(func.count()).select_from(Conversation)).one()
    source_counts = {}
    for source_type in ["calendar", "email", "notes"]:
        c = session.exec(select(func.count()).select_from(SourceItem).where(SourceItem.source_type == source_type)).one()
        source_counts[source_type] = c
    total_sources = sum(source_counts.values())
    vector_count = collection_count()
    llm_budget = get_budget_status()
    return {
        "facts": facts_count,
        "conversations": conversations_count,
        "source_items": source_counts,
        "source_items_total": total_sources,
        "vector_documents": vector_count,
        "llm_budget": llm_budget,
    }


@router.post("/sync/{source}")
async def admin_sync_source(source: str, session: Session = Depends(get_session)) -> dict:
    valid_sources = {"calendar", "email", "notes"}
    if source not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}. Must be one of: calendar, email, notes")
    sync_fns: dict[str, tuple] = {
        "calendar": (sync_calendar_events, {}),
        "email": (sync_emails, {}),
        "notes": (sync_notes, {}),
    }
    sync_fn, kwargs = sync_fns[source]
    try:
        count, changed_ids = await asyncio.to_thread(sync_fn, session, **kwargs)
        embedded = 0
        if changed_ids:
            embedded = await embed_source_items(session, item_ids=changed_ids)
            for item_id in changed_ids:
                item = session.get(SourceItem, item_id)
                if item is not None:
                    item.embedded = True
                    session.add(item)
            session.commit()
        return {
            "status": "ok",
            "source": source,
            "items_synced": count,
            "items_changed": len(changed_ids),
            "items_embedded": embedded,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync {source} failed: {str(e)[:200]}")


@router.get("/llm/budget")
async def admin_llm_budget() -> dict:
    return get_budget_status()


@router.put("/llm/budget")
async def admin_update_llm_budget(body: UpdateBudgetRequest) -> dict:
    try:
        result = update_budget_settings(daily_budget=body.daily_budget, rate_limit_rpm=body.rate_limit_rpm, warning_pct=body.warning_pct)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "ok", "settings": result}


@router.get("/llm/usage/history")
async def admin_llm_usage_history(hours: int = 24) -> dict:
    hours = max(1, min(168, hours))
    result = get_hourly_usage(hours=hours)
    return {"hours": hours, "hourly": result}


@router.get("/llm/usage")
async def admin_llm_usage(days: int = 1) -> dict:
    if days < 1:
        days = 1
    if days > 30:
        days = 30
    by_operation = get_usage_by_operation(days=days)
    return {"days": days, "by_operation": by_operation}


@router.get("/scanner/status")
async def admin_scanner_status() -> dict:
    all_tasks = asyncio.all_tasks()
    scanner_tasks = [t for t in all_tasks if t.get_name().startswith("scanner-")]
    scanners_list = [{"name": t.get_name(), "running": not t.done()} for t in scanner_tasks]
    return {"scanners": scanners_list, "count": len(scanners_list)}
