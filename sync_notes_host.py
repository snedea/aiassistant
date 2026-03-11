#!/usr/bin/env python3
"""Host-side Notes sync script.

Runs on macOS host (where osascript is available), batch-fetches all Apple Notes
via JXA array accessors, and POSTs new/changed notes to the AI assistant backend.

Usage:
    python3 sync_notes_host.py

Cron (every 30 min):
    */30 * * * * /usr/bin/python3 /path/to/aiassistant/sync_notes_host.py >> /tmp/sync_notes.log 2>&1
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_URL = "http://localhost:8000"
API_KEY = ""  # set if API_KEY is configured in .env
DB_PATH = Path(__file__).parent / "data" / "assistant.db"
RECENT_HOURS = 24  # re-check notes modified within this window

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _run_jxa(script: str, timeout: int = 120) -> str:
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout.strip()


def fetch_all_notes_batch() -> list[dict]:
    """Fetch all note properties using JXA batch array accessors. Fast for large collections."""
    script = """
var Notes = Application('Notes');
var ids    = Notes.notes.id();
var names  = Notes.notes.name();
var dates  = Notes.notes.modificationDate();
var bodies = Notes.notes.plaintext();

var out = [];
for (var i = 0; i < ids.length; i++) {
    out.push(ids[i] + '\\t' + names[i] + '\\t' + dates[i].toISOString() + '\\t' + (bodies[i] || ''));
}
out.join('\\n');
"""
    stdout = _run_jxa(script, timeout=120)
    results = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) < 3:
            continue
        results.append({
            "id": parts[0],
            "name": parts[1],
            "modified": parts[2],
            "body": parts[3] if len(parts) > 3 else "",
            "folder": "",
        })
    return results


def get_existing_from_db() -> dict[str, str]:
    """Read existing notes from SQLite. Returns {external_id: content_hash}."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.execute(
            "SELECT external_id, content_hash FROM source_items WHERE source_type = 'notes'"
        )
        return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def push_to_backend(notes: list[dict], chunk_size: int = 100) -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    total = {"items_synced": 0, "items_changed": 0, "items_embedded": 0}
    chunks = [notes[i:i + chunk_size] for i in range(0, len(notes), chunk_size)]
    for idx, chunk in enumerate(chunks):
        logger.info("Pushing chunk %d/%d (%d notes)...", idx + 1, len(chunks), len(chunk))
        payload = json.dumps(chunk).encode()
        req = urllib.request.Request(
            f"{BACKEND_URL}/sources/push/notes",
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        for key in total:
            total[key] += result.get(key, 0)
    return total


def main() -> None:
    logger.info("Starting Apple Notes sync — %s", datetime.now(timezone.utc).isoformat())

    logger.info("Batch-fetching all notes from Apple Notes...")
    try:
        all_notes = fetch_all_notes_batch()
    except Exception as e:
        logger.error("Fetch failed: %s", e)
        sys.exit(1)
    logger.info("Fetched %d notes", len(all_notes))

    existing = get_existing_from_db()
    logger.info("DB has %d existing notes", len(existing))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)

    to_push = []
    for note in all_notes:
        note_id = note["id"]
        is_new = note_id not in existing

        recently_modified = False
        try:
            mod = datetime.fromisoformat(note["modified"].replace("Z", "+00:00"))
            recently_modified = mod > cutoff
        except Exception:
            pass

        if is_new or recently_modified:
            to_push.append(note)

    logger.info("%d notes to push (%d new, %d recently modified)",
                len(to_push),
                sum(1 for n in to_push if n["id"] not in existing),
                sum(1 for n in to_push if n["id"] in existing))

    if not to_push:
        logger.info("Nothing to sync")
        return

    try:
        result = push_to_backend(to_push)
        logger.info(
            "Done: %d synced, %d changed, %d embedded",
            result.get("items_synced", 0),
            result.get("items_changed", 0),
            result.get("items_embedded", 0),
        )
    except Exception as e:
        logger.error("Push failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
