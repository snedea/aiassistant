from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.services.vectorstore import get_collection

logger = logging.getLogger(__name__)


def _run_applescript(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("osascript timed out after 30 seconds")
        raise RuntimeError("osascript timed out after 30 seconds")
    except FileNotFoundError:
        logger.warning("osascript not found")
        raise RuntimeError("osascript not found -- this adapter requires macOS")
    if result.returncode != 0:
        logger.warning("osascript failed: %s", result.stderr.strip())
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _fetch_note_ids_and_names() -> list[dict[str, str]]:
    script = '''tell application "Notes"
    set output to ""
    repeat with n in every note
        set noteId to id of n
        set noteName to name of n
        set folderName to name of container of n
        set modDate to modification date of n
        set output to output & noteId & tab & noteName & tab & folderName & tab & (modDate as string) & linefeed
    end repeat
    return output
end tell'''
    stdout = _run_applescript(script)
    results: list[dict[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            logger.warning("Skipping malformed note line: %s", line[:100])
            continue
        results.append({
            "id": parts[0],
            "name": parts[1],
            "folder": parts[2],
            "modified": parts[3],
        })
    return results


def _escape_applescript_string(value: str) -> str:
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    return value


def _fetch_note_body(note_id: str) -> str:
    safe_id = _escape_applescript_string(note_id)
    script = f'''tell application "Notes"
    set theNote to first note whose id is "{safe_id}"
    return plaintext of theNote
end tell'''
    try:
        return _run_applescript(script)
    except RuntimeError:
        logger.warning("Failed to fetch body for note %s", note_id)
        return ""


def fetch_notes() -> list[dict[str, Any]]:
    note_metas = _fetch_note_ids_and_names()
    results: list[dict[str, Any]] = []
    for note_dict in note_metas:
        body = _fetch_note_body(note_dict["id"])
        results.append({
            "id": note_dict["id"],
            "name": note_dict["name"],
            "folder": note_dict["folder"],
            "modified": note_dict["modified"],
            "body": body,
        })
    logger.info("Fetched %d notes from Apple Notes", len(results))
    return results


def upsert_notes(session: Session, notes: list[dict[str, Any]]) -> tuple[int, list[int], set[str]]:
    """Upsert a list of pre-fetched notes into the DB. Returns (count, changed_ids, fetched_external_ids)."""
    synced_count = 0
    new_items: list[SourceItem] = []
    updated_items: list[SourceItem] = []

    for note_data in notes:
        external_id = note_data["id"]
        stmt = select(SourceItem).where(
            SourceItem.source_type == "notes",
            SourceItem.external_id == external_id,
        )
        existing = session.exec(stmt).first()

        metadata_dict = {"folder": note_data["folder"], "modified": note_data["modified"]}
        metadata_json = json.dumps(metadata_dict)
        new_hash = SourceItem.compute_hash(note_data["name"], note_data["body"], metadata_json)

        if existing is not None:
            if existing.content_hash == new_hash:
                synced_count += 1
                continue
            existing.title = note_data["name"]
            existing.content = note_data["body"]
            existing.raw_metadata = metadata_json
            existing.updated_at = datetime.now(timezone.utc)
            existing.content_hash = new_hash
            existing.embedded = False
            session.add(existing)
            updated_items.append(existing)
        else:
            item = SourceItem(
                source_type="notes",
                external_id=external_id,
                title=note_data["name"],
                content=note_data["body"],
                raw_metadata=metadata_json,
                content_hash=new_hash,
            )
            session.add(item)
            new_items.append(item)

        synced_count += 1

    session.commit()
    changed_ids = [item.id for item in new_items] + [item.id for item in updated_items]
    fetched_ids = {note_data["id"] for note_data in notes}
    return (synced_count, changed_ids, fetched_ids)


def _remove_stale_notes(session: Session, fetched_ids: set[str]) -> None:
    all_notes_stmt = select(SourceItem).where(SourceItem.source_type == "notes")
    all_note_items = session.exec(all_notes_stmt).all()
    stale_items = [item for item in all_note_items if item.external_id not in fetched_ids]
    if not stale_items:
        return
    stale_chroma_ids = [f"notes:{item.external_id}" for item in stale_items]
    try:
        collection = get_collection()
        collection.delete(ids=stale_chroma_ids)
    except Exception as e:
        logger.warning("Failed to delete stale note vectors, keeping DB rows for retry: %s", e)
    else:
        for item in stale_items:
            session.delete(item)
        session.commit()
        logger.info("Deleted %d stale notes from DB and vector store", len(stale_items))


def sync_notes(session: Session) -> tuple[int, list[int]]:
    statement = select(ScanState).where(ScanState.source_type == "notes")
    scan_state = session.exec(statement).first()
    if scan_state is None:
        scan_state = ScanState(source_type="notes", status="idle")
        session.add(scan_state)

    scan_state.status = "syncing"
    scan_state.error_message = None
    session.commit()

    try:
        try:
            notes = fetch_notes()
        except RuntimeError as e:
            if "osascript not found" in str(e):
                # Running in Docker — notes are pushed by the host-side sync script instead.
                scan_state.status = "idle"
                scan_state.error_message = None
                session.commit()
                return (scan_state.items_synced, [])
            raise

        synced_count, changed_ids, fetched_ids = upsert_notes(session, notes)
        _remove_stale_notes(session, fetched_ids)

        scan_state.status = "idle"
        scan_state.last_synced_at = datetime.now(timezone.utc)
        scan_state.items_synced = synced_count
        session.commit()

        logger.info("Notes sync complete: %d notes synced, %d changed", synced_count, len(changed_ids))
        return (synced_count, changed_ids)

    except Exception as e:
        scan_state.status = "error"
        scan_state.error_message = str(e)[:500]
        session.commit()
        logger.error("Notes sync failed: %s", e, exc_info=True)
        raise


def push_notes(session: Session, notes: list[dict[str, Any]]) -> tuple[int, list[int]]:
    """Accept pre-fetched notes from a host-side script (bypasses osascript)."""
    statement = select(ScanState).where(ScanState.source_type == "notes")
    scan_state = session.exec(statement).first()
    if scan_state is None:
        scan_state = ScanState(source_type="notes", status="idle")
        session.add(scan_state)

    scan_state.status = "syncing"
    scan_state.error_message = None
    session.commit()

    try:
        synced_count, changed_ids, _ = upsert_notes(session, notes)

        total_in_db = session.exec(
            select(func.count(SourceItem.id)).where(SourceItem.source_type == "notes")
        ).one()
        scan_state.status = "idle"
        scan_state.last_synced_at = datetime.now(timezone.utc)
        scan_state.items_synced = total_in_db
        session.commit()

        logger.info("Notes push complete: %d notes synced, %d changed", synced_count, len(changed_ids))
        return (synced_count, changed_ids)

    except Exception as e:
        scan_state.status = "error"
        scan_state.error_message = str(e)[:500]
        session.commit()
        logger.error("Notes push failed: %s", e, exc_info=True)
        raise


def get_notes(session: Session, folder: str | None = None, limit: int = 50) -> list[SourceItem]:
    stmt = select(SourceItem).where(SourceItem.source_type == "notes")
    if folder is not None:
        stmt = stmt.where(func.json_extract(SourceItem.raw_metadata, "$.folder") == folder)
    stmt = stmt.order_by(SourceItem.updated_at.desc()).limit(limit)
    return list(session.exec(stmt).all())


def search_notes(session: Session, query: str, limit: int = 10) -> list[SourceItem]:
    query_lower = query.lower()
    stmt = select(SourceItem).where(
        SourceItem.source_type == "notes",
        or_(
            func.lower(SourceItem.title).contains(query_lower),
            func.lower(SourceItem.content).contains(query_lower),
        ),
    ).limit(limit)
    return list(session.exec(stmt).all())
