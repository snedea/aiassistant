from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.adapters.notes import (
    _run_applescript,
    _fetch_note_ids_and_names,
    fetch_notes,
    sync_notes,
    get_notes,
    search_notes,
)


def _make_test_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_run_applescript_success():
    mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
    with patch("subprocess.run", return_value=mock_result):
        result = _run_applescript('return "hello"')
    assert result == "hello"


def test_run_applescript_failure():
    mock_result = MagicMock(returncode=1, stdout="", stderr="error msg")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="osascript failed"):
            _run_applescript('bad script')


def test_fetch_note_ids_and_names():
    fake_output = "note1\tTest Note\tNotes\tMarch 10, 2026 3:00:00 PM"
    with patch("app.adapters.notes._run_applescript", return_value=fake_output):
        result = _fetch_note_ids_and_names()
    assert len(result) == 1
    assert result[0]["id"] == "note1"
    assert result[0]["name"] == "Test Note"
    assert result[0]["folder"] == "Notes"


def test_fetch_note_ids_and_names_with_quotes():
    fake_output = 'note1\tBook: "1984"\tNotes\tMarch 10, 2026 3:00:00 PM'
    with patch("app.adapters.notes._run_applescript", return_value=fake_output):
        result = _fetch_note_ids_and_names()
    assert len(result) == 1
    assert result[0]["name"] == 'Book: "1984"'


def test_sync_notes_creates_source_items():
    session = _make_test_session()
    fake_notes = [{"id": "note-1", "name": "My Note", "folder": "Notes", "modified": "March 10, 2026", "body": "Hello world"}]
    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes):
        count, changed_ids = sync_notes(session)
    assert count == 1
    assert len(changed_ids) == 1
    items = session.exec(select(SourceItem).where(SourceItem.source_type == "notes")).all()
    assert len(items) == 1
    assert items[0].title == "My Note"
    assert items[0].external_id == "note-1"
    assert items[0].content == "Hello world"
    scan = session.exec(select(ScanState).where(ScanState.source_type == "notes")).first()
    assert scan.status == "idle"
    assert scan.items_synced == 1


def test_sync_notes_updates_existing():
    session = _make_test_session()
    existing = SourceItem(source_type="notes", external_id="note-1", title="Old Title", content="old body", raw_metadata="{}")
    session.add(existing)
    session.commit()
    fake_notes = [{"id": "note-1", "name": "New Title", "folder": "Notes", "modified": "March 10, 2026", "body": "new body"}]
    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes):
        count, changed_ids = sync_notes(session)
    items = session.exec(select(SourceItem).where(SourceItem.source_type == "notes")).all()
    assert len(items) == 1
    assert items[0].title == "New Title"
    assert items[0].content == "new body"


def test_get_notes_all():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="n1", title="A", content="aaa", raw_metadata="{}"))
    session.add(SourceItem(source_type="notes", external_id="n2", title="B", content="bbb", raw_metadata="{}"))
    session.commit()
    result = get_notes(session)
    assert len(result) == 2


def test_get_notes_filter_by_folder():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="n1", title="A", content="", raw_metadata=json.dumps({"folder": "Work"})))
    session.add(SourceItem(source_type="notes", external_id="n2", title="B", content="", raw_metadata=json.dumps({"folder": "Personal"})))
    session.commit()
    result = get_notes(session, folder="Work")
    assert len(result) == 1
    assert result[0].title == "A"


def test_get_notes_folder_filter_applied_before_limit():
    """LIMIT must apply after folder filtering, not before."""
    session = _make_test_session()
    # Create 3 Personal notes (newer) and 2 Work notes (older)
    for i in range(3):
        session.add(SourceItem(
            source_type="notes",
            external_id=f"personal-{i}",
            title=f"Personal {i}",
            content="",
            raw_metadata=json.dumps({"folder": "Personal"}),
            updated_at=datetime(2026, 3, 10, 12, 0, i, tzinfo=timezone.utc),
        ))
    for i in range(2):
        session.add(SourceItem(
            source_type="notes",
            external_id=f"work-{i}",
            title=f"Work {i}",
            content="",
            raw_metadata=json.dumps({"folder": "Work"}),
            updated_at=datetime(2026, 3, 9, 12, 0, i, tzinfo=timezone.utc),
        ))
    session.commit()
    # With the old bug: limit=3 fetches 3 newest (all Personal), then folder
    # filter returns 0 Work notes. With the fix: folder filter is in SQL,
    # so limit=3 returns up to 3 Work notes.
    result = get_notes(session, folder="Work", limit=3)
    assert len(result) == 2
    assert all(r.title.startswith("Work") for r in result)


def test_search_notes():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="n1", title="Shopping List", content="milk eggs bread", raw_metadata="{}"))
    session.add(SourceItem(source_type="notes", external_id="n2", title="Meeting Notes", content="discuss project timeline", raw_metadata="{}"))
    session.commit()
    result = search_notes(session, query="shopping")
    assert len(result) == 1
    assert result[0].external_id == "n1"
    result = search_notes(session, query="timeline")
    assert len(result) == 1
    assert result[0].external_id == "n2"


def test_search_notes_case_insensitive():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="n1", title="Shopping List", content="milk eggs bread", raw_metadata="{}"))
    session.add(SourceItem(source_type="notes", external_id="n2", title="Meeting Notes", content="discuss Project Timeline", raw_metadata="{}"))
    session.commit()
    result = search_notes(session, query="SHOPPING")
    assert len(result) == 1
    assert result[0].external_id == "n1"
    result = search_notes(session, query="PROJECT")
    assert len(result) == 1
    assert result[0].external_id == "n2"


def test_sync_notes_error_updates_scan_state():
    session = _make_test_session()
    with patch("app.adapters.notes.fetch_notes", side_effect=RuntimeError("osascript not found")):
        with pytest.raises(RuntimeError):
            sync_notes(session)
    scan = session.exec(select(ScanState).where(ScanState.source_type == "notes")).first()
    assert scan.status == "error"
    assert "osascript not found" in scan.error_message


def test_sync_notes_skips_unchanged():
    session = _make_test_session()
    fake_notes = [{"id": "note-1", "name": "My Note", "folder": "Notes", "modified": "March 10, 2026", "body": "Hello world"}]

    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes):
        count1, changed_ids1 = sync_notes(session)

    assert count1 == 1
    assert len(changed_ids1) == 1

    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes):
        count2, changed_ids2 = sync_notes(session)

    assert count2 == 1
    assert len(changed_ids2) == 0


def test_sync_notes_stale_delete_removes_db_rows_after_vector_delete():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="note-1", title="Keep", content="keep", raw_metadata="{}"))
    session.add(SourceItem(source_type="notes", external_id="note-stale", title="Stale", content="stale", raw_metadata="{}"))
    session.commit()
    fake_notes = [{"id": "note-1", "name": "Keep", "folder": "Notes", "modified": "March 10, 2026", "body": "keep"}]
    mock_collection = MagicMock()
    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes), \
         patch("app.adapters.notes.get_collection", return_value=mock_collection):
        sync_notes(session)
    mock_collection.delete.assert_called_once_with(ids=["notes:note-stale"])
    items = session.exec(select(SourceItem).where(SourceItem.source_type == "notes")).all()
    assert len(items) == 1
    assert items[0].external_id == "note-1"


def test_sync_notes_stale_delete_keeps_db_rows_on_vector_failure():
    session = _make_test_session()
    session.add(SourceItem(source_type="notes", external_id="note-1", title="Keep", content="keep", raw_metadata="{}"))
    session.add(SourceItem(source_type="notes", external_id="note-stale", title="Stale", content="stale", raw_metadata="{}"))
    session.commit()
    fake_notes = [{"id": "note-1", "name": "Keep", "folder": "Notes", "modified": "March 10, 2026", "body": "keep"}]
    mock_collection = MagicMock()
    mock_collection.delete.side_effect = RuntimeError("ChromaDB unavailable")
    with patch("app.adapters.notes.fetch_notes", return_value=fake_notes), \
         patch("app.adapters.notes.get_collection", return_value=mock_collection):
        sync_notes(session)
    mock_collection.delete.assert_called_once_with(ids=["notes:note-stale"])
    items = session.exec(select(SourceItem).where(SourceItem.source_type == "notes")).all()
    assert len(items) == 2
    assert {item.external_id for item in items} == {"note-1", "note-stale"}
    scan = session.exec(select(ScanState).where(ScanState.source_type == "notes")).first()
    assert scan.status == "idle"
