from __future__ import annotations

import json
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, SQLModel, create_engine

from app.models.source_item import SourceItem
from app.services.daily_digest import _get_todays_events


def _make_test_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _insert_event(session: Session, external_id: str, title: str, dtstart_str: str, dtstart_utc: datetime | None) -> None:
    raw_metadata = json.dumps({"dtstart": dtstart_str, "dtend": "", "location": "", "attendees": []})
    item = SourceItem(source_type="calendar", external_id=external_id, title=title, content="", raw_metadata=raw_metadata, dtstart_utc=dtstart_utc)
    session.add(item)
    session.commit()


def test_get_todays_events_returns_timed_events_for_today() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    today_local = datetime.now(tz).date()
    event_dt = datetime.combine(today_local, time(14, 0), tzinfo=tz).astimezone(timezone.utc)
    _insert_event(session, "today-evt", "Today Meeting", event_dt.isoformat(), event_dt)
    result = _get_todays_events(session, tz)
    assert len(result) == 1
    assert result[0]["title"] == "Today Meeting"


def test_get_todays_events_excludes_yesterday_events() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    yesterday_local = datetime.now(tz).date() - timedelta(days=1)
    event_dt = datetime.combine(yesterday_local, time(14, 0), tzinfo=tz).astimezone(timezone.utc)
    _insert_event(session, "yesterday-evt", "Yesterday Meeting", event_dt.isoformat(), event_dt)
    result = _get_todays_events(session, tz)
    assert len(result) == 0


def test_get_todays_events_excludes_tomorrow_events() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    tomorrow_local = datetime.now(tz).date() + timedelta(days=1)
    event_dt = datetime.combine(tomorrow_local, time(14, 0), tzinfo=tz).astimezone(timezone.utc)
    _insert_event(session, "tomorrow-evt", "Tomorrow Meeting", event_dt.isoformat(), event_dt)
    result = _get_todays_events(session, tz)
    assert len(result) == 0


def test_get_todays_events_returns_allday_events_for_today() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    today_local = datetime.now(tz).date()
    dtstart_str = today_local.isoformat() + " (all-day)"
    _insert_event(session, "allday-evt", "All Day Event", dtstart_str, None)
    result = _get_todays_events(session, tz)
    assert len(result) == 1
    assert result[0]["title"] == "All Day Event"


def test_get_todays_events_excludes_allday_events_for_other_dates() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    yesterday_local = datetime.now(tz).date() - timedelta(days=1)
    dtstart_str = yesterday_local.isoformat() + " (all-day)"
    _insert_event(session, "allday-yesterday", "Yesterday All Day", dtstart_str, None)
    result = _get_todays_events(session, tz)
    assert len(result) == 0


def test_get_todays_events_excludes_non_calendar_items() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    today_local = datetime.now(tz).date()
    event_dt = datetime.combine(today_local, time(14, 0), tzinfo=tz).astimezone(timezone.utc)
    item = SourceItem(source_type="email", external_id="email-1", title="Some Email", content="", raw_metadata="{}", dtstart_utc=event_dt)
    session.add(item)
    session.commit()
    result = _get_todays_events(session, tz)
    assert len(result) == 0


def test_get_todays_events_mixed_timed_and_allday() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    today_local = datetime.now(tz).date()
    dtstart_str = today_local.isoformat() + " (all-day)"
    _insert_event(session, "allday-mixed", "All Day", dtstart_str, None)
    event_dt = datetime.combine(today_local, time(14, 0), tzinfo=tz).astimezone(timezone.utc)
    _insert_event(session, "timed-mixed", "Afternoon Meeting", event_dt.isoformat(), event_dt)
    result = _get_todays_events(session, tz)
    assert len(result) == 2
    assert {r["title"] for r in result} == {"All Day", "Afternoon Meeting"}


def test_get_todays_events_empty_table() -> None:
    session = _make_test_session()
    tz = ZoneInfo("America/Chicago")
    result = _get_todays_events(session, tz)
    assert result == []
