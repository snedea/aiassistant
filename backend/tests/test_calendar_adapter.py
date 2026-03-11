from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.source_item import SourceItem
from app.models.scan_state import ScanState
from app.adapters.calendar import (
    _parse_vevent,
    _parse_dtstart_utc,
    sync_calendar_events,
    get_upcoming_events,
)


def _make_test_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_parse_vevent_basic():
    vevent = MagicMock()

    dtstart_mock = MagicMock()
    dtstart_mock.dt = datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)
    dtend_mock = MagicMock()
    dtend_mock.dt = datetime(2026, 3, 10, 16, 0, tzinfo=timezone.utc)

    def vevent_get(key, default=None):
        mapping = {
            "UID": "test-uid-123",
            "SUMMARY": "Team Meeting",
            "DESCRIPTION": "Weekly standup",
            "LOCATION": "Room 4",
            "STATUS": "CONFIRMED",
            "RRULE": None,
            "ATTENDEE": None,
            "DTSTART": dtstart_mock,
            "DTEND": dtend_mock,
        }
        if key in mapping:
            return mapping[key]
        return default

    vevent.get = vevent_get

    result = _parse_vevent(vevent)
    assert result is not None
    assert result["uid"] == "test-uid-123"
    assert result["summary"] == "Team Meeting"
    assert result["location"] == "Room 4"
    assert "2026-03-10" in result["dtstart"]


def test_parse_vevent_no_uid():
    vevent = MagicMock()

    def vevent_get(key, default=None):
        if key == "UID":
            return None
        return default

    vevent.get = vevent_get

    result = _parse_vevent(vevent)
    assert result is None


def test_sync_calendar_events_creates_source_items():
    session = _make_test_session()
    fake_events = [
        {
            "uid": "evt-1",
            "summary": "Meeting",
            "description": "desc",
            "location": "Room 1",
            "dtstart": "2026-03-10T15:00:00+00:00",
            "dtend": "2026-03-10T16:00:00+00:00",
            "attendees": [],
            "status": "CONFIRMED",
            "rrule": "",
        }
    ]

    with patch("app.adapters.calendar.fetch_events", return_value=fake_events):
        count, changed_ids = sync_calendar_events(session)

    assert count == 1
    assert len(changed_ids) == 1
    items = session.exec(
        select(SourceItem).where(SourceItem.source_type == "calendar")
    ).all()
    assert len(items) == 1
    assert items[0].title == "Meeting"
    assert items[0].external_id == "evt-1"
    assert items[0].content_hash != ""

    scan = session.exec(
        select(ScanState).where(ScanState.source_type == "calendar")
    ).first()
    assert scan is not None
    assert scan.status == "idle"
    assert scan.items_synced == 1


def test_sync_calendar_events_updates_existing():
    session = _make_test_session()
    existing = SourceItem(
        source_type="calendar",
        external_id="evt-1",
        title="Old Title",
        content="old desc",
        raw_metadata="{}",
    )
    session.add(existing)
    session.commit()

    fake_events = [
        {
            "uid": "evt-1",
            "summary": "New Title",
            "description": "new desc",
            "location": "Room 2",
            "dtstart": "2026-03-10T15:00:00+00:00",
            "dtend": "2026-03-10T16:00:00+00:00",
            "attendees": [],
            "status": "CONFIRMED",
            "rrule": "",
        }
    ]

    with patch("app.adapters.calendar.fetch_events", return_value=fake_events):
        count, changed_ids = sync_calendar_events(session)

    assert len(changed_ids) == 1
    items = session.exec(
        select(SourceItem).where(SourceItem.source_type == "calendar")
    ).all()
    assert len(items) == 1
    assert items[0].title == "New Title"
    assert items[0].content_hash != ""


def test_parse_dtstart_utc() -> None:
    assert _parse_dtstart_utc("") is None
    assert _parse_dtstart_utc("2026-03-10 (all-day)") is None
    assert _parse_dtstart_utc("2026-03-10T15:00:00+00:00") == datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)
    assert _parse_dtstart_utc("not-a-date") is None


def test_get_upcoming_events():
    session = _make_test_session()
    now = datetime.now(timezone.utc)

    soon_dt = now + timedelta(minutes=5)
    later_dt = now + timedelta(hours=2)

    soon_item = SourceItem(
        source_type="calendar",
        external_id="soon-evt",
        title="Soon",
        content="",
        raw_metadata=json.dumps({"dtstart": soon_dt.isoformat(), "dtend": ""}),
        dtstart_utc=soon_dt,
    )
    later_item = SourceItem(
        source_type="calendar",
        external_id="later-evt",
        title="Later",
        content="",
        raw_metadata=json.dumps({"dtstart": later_dt.isoformat(), "dtend": ""}),
        dtstart_utc=later_dt,
    )
    allday_item = SourceItem(
        source_type="calendar",
        external_id="allday-evt",
        title="All Day",
        content="",
        raw_metadata=json.dumps({"dtstart": "2026-03-10 (all-day)", "dtend": ""}),
        dtstart_utc=None,
    )
    session.add(soon_item)
    session.add(later_item)
    session.add(allday_item)
    session.commit()

    upcoming = get_upcoming_events(session, within_minutes=15)
    assert len(upcoming) == 1
    assert upcoming[0].external_id == "soon-evt"


def test_get_upcoming_events_empty_when_no_calendar_events() -> None:
    session = _make_test_session()
    upcoming = get_upcoming_events(session, within_minutes=15)
    assert len(upcoming) == 0


def test_sync_sets_dtstart_utc() -> None:
    session = _make_test_session()
    fake_events = [
        {
            "uid": "evt-dt",
            "summary": "Timed",
            "description": "",
            "location": "",
            "dtstart": "2026-03-10T15:00:00+00:00",
            "dtend": "2026-03-10T16:00:00+00:00",
            "attendees": [],
            "status": "CONFIRMED",
            "rrule": "",
        }
    ]

    with patch("app.adapters.calendar.fetch_events", return_value=fake_events):
        sync_calendar_events(session)

    item = session.exec(select(SourceItem).where(SourceItem.external_id == "evt-dt")).first()
    assert item.dtstart_utc is not None
    assert item.dtstart_utc.year == 2026
    assert item.dtstart_utc.month == 3
    assert item.dtstart_utc.day == 10
    assert item.dtstart_utc.hour == 15


def test_sync_calendar_events_skips_unchanged():
    session = _make_test_session()
    fake_events = [
        {
            "uid": "evt-1",
            "summary": "Meeting",
            "description": "desc",
            "location": "Room 1",
            "dtstart": "2026-03-10T15:00:00+00:00",
            "dtend": "2026-03-10T16:00:00+00:00",
            "attendees": [],
            "status": "CONFIRMED",
            "rrule": "",
        }
    ]

    with patch("app.adapters.calendar.fetch_events", return_value=fake_events):
        count1, changed_ids1 = sync_calendar_events(session)

    assert count1 == 1
    assert len(changed_ids1) == 1

    with patch("app.adapters.calendar.fetch_events", return_value=fake_events):
        count2, changed_ids2 = sync_calendar_events(session)

    assert count2 == 1
    assert len(changed_ids2) == 0
