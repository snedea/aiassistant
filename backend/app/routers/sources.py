from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import require_auth
from app.database import get_session
from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.adapters.calendar import sync_calendar_events, get_upcoming_events
from app.adapters.notes import sync_notes, push_notes, get_notes, search_notes
from app.adapters.email import sync_emails, get_emails, search_emails
from app.services.email_summarizer import get_recent_summaries, get_email_summaries, summarize_new_emails
from app.services.embedding import embed_source_items, semantic_search
from app.services.calendar_alerter import get_recent_alerts, check_upcoming_alerts
from app.services.triage_service import get_recent_triages, get_item_triages, triage_items
from app.services.health_monitor import get_source_health_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"], dependencies=[Depends(require_auth)])


@router.post("/sync/calendar")
async def sync_calendar(session: Session = Depends(get_session)) -> dict:
    try:
        count, changed_ids = await asyncio.to_thread(sync_calendar_events, session)
        embedded = 0
        if changed_ids:
            embedded = await embed_source_items(session, item_ids=changed_ids)
            for item_id in changed_ids:
                item = session.get(SourceItem, item_id)
                if item is not None:
                    item.embedded = True
                    session.add(item)
            session.commit()
        return {"status": "ok", "source": "calendar", "items_synced": count, "items_changed": len(changed_ids), "items_embedded": embedded}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendar sync failed: {e}")


@router.get("/calendar/upcoming")
async def upcoming_events(
    within_minutes: int = 15,
    session: Session = Depends(get_session),
) -> dict:
    events = get_upcoming_events(session, within_minutes=within_minutes)
    response_list = [
        {
            "id": event.id,
            "title": event.title,
            "content": event.content,
            "raw_metadata": json.loads(event.raw_metadata),
            "ingested_at": event.ingested_at.isoformat(),
            "updated_at": event.updated_at.isoformat(),
        }
        for event in events
    ]
    return {"events": response_list, "count": len(response_list)}


@router.get("/calendar/alerts")
async def calendar_alerts() -> dict:
    alerts = get_recent_alerts()
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/calendar/alerts/check")
async def trigger_alert_check(
    within_minutes: int | None = None,
    session: Session = Depends(get_session),
) -> dict:
    new_alerts = check_upcoming_alerts(session, within_minutes=within_minutes)
    return {"new_alerts": new_alerts, "count": len(new_alerts)}


@router.post("/sync/notes")
async def sync_notes_endpoint(session: Session = Depends(get_session)) -> dict:
    try:
        count, changed_ids = await asyncio.to_thread(sync_notes, session)
        embedded = 0
        if changed_ids:
            embedded = await embed_source_items(session, item_ids=changed_ids)
            for item_id in changed_ids:
                item = session.get(SourceItem, item_id)
                if item is not None:
                    item.embedded = True
                    session.add(item)
            session.commit()
        return {"status": "ok", "source": "notes", "items_synced": count, "items_changed": len(changed_ids), "items_embedded": embedded}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Notes sync failed: {e}")


class NoteItem(BaseModel):
    id: str
    name: str
    folder: str
    modified: str
    body: str


@router.post("/push/notes")
async def push_notes_endpoint(
    notes: list[NoteItem],
    session: Session = Depends(get_session),
) -> dict:
    """Accept notes from a host-side script (used instead of osascript inside Docker)."""
    try:
        note_dicts = [n.model_dump() for n in notes]
        count, changed_ids = await asyncio.to_thread(push_notes, session, note_dicts)
        embedded = 0
        if changed_ids:
            embedded = await embed_source_items(session, item_ids=changed_ids)
            for item_id in changed_ids:
                item = session.get(SourceItem, item_id)
                if item is not None:
                    item.embedded = True
                    session.add(item)
            session.commit()
        return {"status": "ok", "source": "notes", "items_synced": count, "items_changed": len(changed_ids), "items_embedded": embedded}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Notes push failed: {e}")


@router.get("/notes")
async def list_notes(
    folder: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    notes = get_notes(session, folder=folder, limit=limit)
    response_list = [
        {
            "id": note.id,
            "title": note.title,
            "content": note.content[:200],
            "raw_metadata": json.loads(note.raw_metadata),
            "ingested_at": note.ingested_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }
        for note in notes
    ]
    return {"notes": response_list, "count": len(response_list)}


@router.get("/notes/search")
async def search_notes_endpoint(
    q: str = "",
    limit: int = 10,
    session: Session = Depends(get_session),
) -> dict:
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    notes = search_notes(session, query=q, limit=limit)
    response_list = [
        {
            "id": note.id,
            "title": note.title,
            "content": note.content[:200],
            "raw_metadata": json.loads(note.raw_metadata),
            "ingested_at": note.ingested_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }
        for note in notes
    ]
    return {"notes": response_list, "count": len(response_list)}


@router.post("/sync/email")
async def sync_email(
    folder: str = "INBOX",
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    try:
        count, changed_ids = await asyncio.to_thread(sync_emails, session, folder=folder, limit=limit)
        embedded = 0
        if changed_ids:
            embedded = await embed_source_items(session, item_ids=changed_ids)
            for item_id in changed_ids:
                item = session.get(SourceItem, item_id)
                if item is not None:
                    item.embedded = True
                    session.add(item)
            session.commit()
        return {"status": "ok", "source": "email", "items_synced": count, "items_changed": len(changed_ids), "items_embedded": embedded}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Email sync failed: {e}")


@router.get("/emails")
async def list_emails(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    emails = get_emails(session, limit=limit)
    response_list = [
        {
            "id": em.id,
            "title": em.title,
            "content": em.content[:200],
            "raw_metadata": json.loads(em.raw_metadata),
            "ingested_at": em.ingested_at.isoformat(),
            "updated_at": em.updated_at.isoformat(),
        }
        for em in emails
    ]
    return {"emails": response_list, "count": len(response_list)}


@router.get("/emails/search")
async def search_emails_endpoint(
    q: str = "",
    limit: int = 10,
    session: Session = Depends(get_session),
) -> dict:
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    emails = search_emails(session, query=q, limit=limit)
    response_list = [
        {
            "id": em.id,
            "title": em.title,
            "content": em.content[:200],
            "raw_metadata": json.loads(em.raw_metadata),
            "ingested_at": em.ingested_at.isoformat(),
            "updated_at": em.updated_at.isoformat(),
        }
        for em in emails
    ]
    return {"emails": response_list, "count": len(response_list)}


@router.get("/emails/summaries")
async def list_email_summaries(
    importance: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    summaries = get_email_summaries(session, importance=importance, limit=limit)
    response_list = [
        {
            "id": s.id,
            "source_item_id": s.source_item_id,
            "external_id": s.external_id,
            "importance": s.importance,
            "summary": s.summary,
            "from": s.from_addr,
            "subject": s.subject,
            "created_at": s.created_at.isoformat(),
        }
        for s in summaries
    ]
    return {"summaries": response_list, "count": len(response_list)}


@router.get("/emails/summaries/recent")
async def recent_email_summaries(session: Session = Depends(get_session)) -> dict:
    summaries = get_recent_summaries()
    if not summaries:
        db_summaries = get_email_summaries(session, limit=20)
        summaries = [
            {
                "importance": s.importance,
                "summary": s.summary,
                "subject": s.subject,
                "from": s.from_addr,
                "created_at": s.created_at.isoformat(),
            }
            for s in db_summaries
        ]
    return {"summaries": summaries, "count": len(summaries)}


@router.post("/emails/summarize")
async def trigger_email_summarize(
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(SourceItem).where(SourceItem.source_type == "email")
    stmt = stmt.order_by(SourceItem.updated_at.desc()).limit(limit)
    items = list(session.exec(stmt).all())
    item_ids = [item.id for item in items]
    try:
        summaries = await summarize_new_emails(session, item_ids)
        return {
            "status": "ok",
            "emails_processed": len(item_ids),
            "summaries_created": len(summaries),
            "summaries": [
                {
                    "importance": s.importance,
                    "summary": s.summary,
                    "subject": s.subject,
                    "from": s.from_addr,
                }
                for s in summaries
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Email summarization failed: {e}")


@router.post("/embed")
async def embed_all(
    source_type: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    try:
        embedded = await embed_source_items(session, source_type=source_type)
        return {"status": "ok", "items_embedded": embedded}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")


@router.get("/search")
async def search_sources(
    q: str = "",
    source_type: str | None = None,
    limit: int = 10,
) -> dict:
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    try:
        results = await semantic_search(query_text=q, source_type=source_type, n_results=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")


@router.get("/items")
async def list_source_items(
    source_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(SourceItem)
    if source_type is not None:
        stmt = stmt.where(SourceItem.source_type == source_type)
    stmt = stmt.order_by(SourceItem.updated_at.desc()).limit(limit)

    items = session.exec(stmt).all()
    response_list = [
        {
            "id": item.id,
            "source_type": item.source_type,
            "external_id": item.external_id,
            "title": item.title,
            "content": item.content[:200],
            "raw_metadata": json.loads(item.raw_metadata),
            "ingested_at": item.ingested_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in items
    ]
    return {"items": response_list, "count": len(response_list)}


@router.get("/scan-state")
async def get_scan_states(session: Session = Depends(get_session)) -> dict:
    stmt = select(ScanState)
    states = session.exec(stmt).all()
    response_list = [
        {
            "id": state.id,
            "source_type": state.source_type,
            "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
            "last_cursor": state.last_cursor,
            "status": state.status,
            "error_message": state.error_message,
            "items_synced": state.items_synced,
        }
        for state in states
    ]
    return {"scan_states": response_list}


@router.get("/health")
async def source_health(session: Session = Depends(get_session)) -> dict:
    statuses = get_source_health_status(session)
    return {"sources": statuses, "count": len(statuses)}


@router.get("/scanner/status")
async def scanner_status() -> dict:
    all_tasks = asyncio.all_tasks()
    scanner_tasks = [t for t in all_tasks if t.get_name().startswith("scanner-")]
    return {
        "scanners": [{"name": t.get_name(), "running": not t.done()} for t in scanner_tasks],
        "count": len(scanner_tasks),
    }


@router.get("/triage")
async def list_triages(
    source_type: str | None = None,
    priority: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    triages = get_item_triages(session, source_type=source_type, priority=priority, limit=limit)
    response_list = [
        {
            "id": t.id,
            "source_item_id": t.source_item_id,
            "source_type": t.source_type,
            "external_id": t.external_id,
            "priority": t.priority,
            "summary": t.summary,
            "title": t.title,
            "created_at": t.created_at.isoformat(),
        }
        for t in triages
    ]
    return {"triages": response_list, "count": len(response_list)}


@router.get("/triage/recent")
async def recent_triages() -> dict:
    triages = get_recent_triages()
    return {"triages": triages, "count": len(triages)}


@router.post("/triage/run")
async def trigger_triage(
    source_type: str = "calendar",
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    if source_type not in ("calendar", "notes"):
        raise HTTPException(status_code=400, detail="source_type must be 'calendar' or 'notes'")
    stmt = select(SourceItem).where(SourceItem.source_type == source_type)
    stmt = stmt.order_by(SourceItem.updated_at.desc()).limit(limit)
    items = list(session.exec(stmt).all())
    item_ids = [item.id for item in items]
    try:
        triages = await triage_items(session, item_ids, source_type)
        return {
            "status": "ok",
            "source_type": source_type,
            "items_processed": len(item_ids),
            "triages_created": len(triages),
            "triages": [
                {
                    "priority": t.priority,
                    "summary": t.summary,
                    "title": t.title,
                }
                for t in triages
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Triage failed: {e}")
