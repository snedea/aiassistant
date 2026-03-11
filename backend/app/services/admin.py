from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone

import httpx
from sqlmodel import Session, select, delete, func

from app.config import get_settings
from app.models.conversation import Conversation
from app.models.fact import Fact
from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.services.vectorstore import get_collection
from app.services.embedding import embed_source_items

logger = logging.getLogger(__name__)


async def reindex_vectorstore(session: Session) -> dict[str, int]:
    collection = get_collection()
    old_count = collection.count()
    all_items = list(session.exec(select(SourceItem)).all())
    if len(all_items) == 0:
        existing = collection.get(include=[])
        existing_ids = existing["ids"]
        if len(existing_ids) > 0:
            for i in range(0, len(existing_ids), 500):
                collection.delete(ids=existing_ids[i:i + 500])
        return {"old_count": old_count, "new_count": 0}
    expected_chroma_ids = {f"{item.source_type}:{item.external_id}" for item in all_items}
    all_db_ids = [item.id for item in all_items]
    # Embed all items using upsert -- no upfront delete, so partial failure
    # leaves existing vectors intact instead of permanently losing them
    embedded = 0
    for i in range(0, len(all_db_ids), 50):
        batch_ids = all_db_ids[i:i + 50]
        batch_count = await embed_source_items(session, item_ids=batch_ids)
        embedded += batch_count
    # Only after all embedding succeeds, prune orphaned vectors
    existing = collection.get(include=[])
    current_chroma_ids = set(existing["ids"])
    orphan_ids = list(current_chroma_ids - expected_chroma_ids)
    if len(orphan_ids) > 0:
        for i in range(0, len(orphan_ids), 500):
            collection.delete(ids=orphan_ids[i:i + 500])
        logger.info("Deleted %d orphaned vectors from ChromaDB", len(orphan_ids))
    # Mark all source items as embedded after full reindex
    all_items_stmt = select(SourceItem).where(SourceItem.embedded == False)
    unembedded_items = session.exec(all_items_stmt).all()
    for item in unembedded_items:
        item.embedded = True
        session.add(item)
    session.commit()
    return {"old_count": old_count, "new_count": embedded}


def clear_facts(session: Session, category: str | None = None) -> int:
    stmt = select(Fact).where(Fact.active == True)
    if category is not None:
        stmt = stmt.where(Fact.category == category)
    facts = list(session.exec(stmt).all())
    for fact in facts:
        fact.active = False
        fact.updated_at = datetime.now(timezone.utc)
        session.add(fact)
    session.commit()
    return len(facts)


def clear_conversations(session: Session) -> int:
    stmt = select(func.count()).select_from(Conversation)
    count = session.exec(stmt).one()
    session.exec(delete(Conversation))
    session.commit()
    return count


def clear_source_items(session: Session, source_type: str | None = None) -> int:
    stmt = select(SourceItem)
    if source_type is not None:
        stmt = stmt.where(SourceItem.source_type == source_type)
    items = list(session.exec(stmt).all())
    if len(items) == 0:
        return 0
    chroma_ids = [f"{item.source_type}:{item.external_id}" for item in items]
    # Delete vectors from ChromaDB FIRST; only commit DB deletion on success
    try:
        collection = get_collection()
        for i in range(0, len(chroma_ids), 500):
            collection.delete(ids=chroma_ids[i:i + 500])
    except Exception as e:
        logger.warning("Failed to delete vectors from ChromaDB, keeping DB rows for retry: %s", e)
        return 0
    else:
        del_stmt = delete(SourceItem)
        if source_type is not None:
            del_stmt = del_stmt.where(SourceItem.source_type == source_type)
        session.exec(del_stmt)
        if source_type is not None:
            scan_stmt = select(ScanState).where(ScanState.source_type == source_type)
        else:
            scan_stmt = select(ScanState)
        for state in session.exec(scan_stmt).all():
            state.last_synced_at = None
            state.last_cursor = None
            state.items_synced = 0
            state.status = "idle"
            state.error_message = None
            session.add(state)
        session.commit()
    return len(items)


async def test_connection_ollama() -> dict[str, str | bool]:
    settings = get_settings()
    if settings.ollama_base_url == "":
        return {"name": "ollama", "configured": False, "reachable": False, "error": "OLLAMA_BASE_URL not set"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
        if resp.status_code == 200:
            return {"name": "ollama", "configured": True, "reachable": True, "detail": f"Models: {len(resp.json().get('models', []))}"}
        else:
            return {"name": "ollama", "configured": True, "reachable": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "ollama", "configured": True, "reachable": False, "error": str(e)[:200]}


async def test_connection_caldav() -> dict[str, str | bool]:
    settings = get_settings()
    if settings.caldav_url == "":
        return {"name": "caldav", "configured": False, "reachable": False, "error": "CALDAV_URL not set"}
    try:
        import caldav as caldav_lib
        client = caldav_lib.DAVClient(url=settings.caldav_url, username=settings.caldav_username, password=settings.caldav_password)
        principal = await asyncio.to_thread(client.principal)
        calendars = await asyncio.to_thread(principal.calendars)
        return {"name": "caldav", "configured": True, "reachable": True, "detail": f"Calendars: {len(calendars)}"}
    except Exception as e:
        return {"name": "caldav", "configured": True, "reachable": False, "error": str(e)[:200]}


async def test_connection_imap() -> dict[str, str | bool]:
    settings = get_settings()
    if settings.imap_host == "":
        return {"name": "imap", "configured": False, "reachable": False, "error": "IMAP_HOST not set"}
    try:
        import imapclient

        def _test():
            client = imapclient.IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True)
            try:
                client.login(settings.imap_username, settings.imap_password)
                folders = client.list_folders()
                return len(folders)
            finally:
                client.logout()

        folder_count = await asyncio.to_thread(_test)
        return {"name": "imap", "configured": True, "reachable": True, "detail": f"Folders: {folder_count}"}
    except Exception as e:
        return {"name": "imap", "configured": True, "reachable": False, "error": str(e)[:200]}


async def test_connection_notes() -> dict[str, str | bool]:
    try:
        def _test():
            result = subprocess.run(["osascript", "-e", 'tell application "Notes" to count of notes'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or f"osascript exited with code {result.returncode}")
            return result.stdout.strip()

        output = await asyncio.to_thread(_test)
        return {"name": "notes", "configured": True, "reachable": True, "detail": f"Notes: {output}"}
    except FileNotFoundError:
        return {"name": "notes", "configured": False, "reachable": False, "error": "osascript not available (not macOS)"}
    except Exception as e:
        return {"name": "notes", "configured": True, "reachable": False, "error": str(e)[:200]}


async def test_connection_slack() -> dict[str, str | bool]:
    settings = get_settings()
    has_webhook = settings.slack_webhook_url != ""
    has_bot = settings.slack_bot_token != ""
    if not has_webhook and not has_bot:
        return {"name": "slack", "configured": False, "reachable": False, "error": "No SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN set"}
    try:
        if has_bot:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {settings.slack_bot_token}"})
            data = resp.json()
            if data.get("ok"):
                return {"name": "slack", "configured": True, "reachable": True, "detail": f"Team: {data.get('team', 'unknown')}"}
            else:
                return {"name": "slack", "configured": True, "reachable": False, "error": data.get("error", "unknown error")}
        else:
            return {"name": "slack", "configured": True, "reachable": True, "detail": "Webhook configured (not tested)"}
    except Exception as e:
        return {"name": "slack", "configured": True, "reachable": False, "error": str(e)[:200]}


async def test_all_connections() -> list[dict[str, str | bool]]:
    results = await asyncio.gather(
        test_connection_ollama(),
        test_connection_caldav(),
        test_connection_imap(),
        test_connection_notes(),
        test_connection_slack(),
        return_exceptions=True,
    )
    output = []
    for result in results:
        if isinstance(result, Exception):
            output.append({"name": "unknown", "configured": False, "reachable": False, "error": str(result)[:200]})
        else:
            output.append(result)
    return output
