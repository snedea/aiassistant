from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.source_item import SourceItem
from app.services.calendar_alerter import (
    _event_alert_key,
    check_upcoming_alerts,
    get_recent_alerts,
    clear_stale_alert_keys,
    _recent_alerts,
)
from app.models.alerted_event import AlertedEvent


def _make_test_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_event_alert_key() -> None:
    result = _event_alert_key("evt-1", "2026-03-10T15:00:00+00:00")
    assert result == "evt-1|2026-03-10T15:00:00+00:00"


def test_check_upcoming_alerts_new_event() -> None:
    _recent_alerts.clear()
    session = _make_test_session()
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    item = SourceItem(
        source_type="calendar",
        external_id="evt-1",
        title="Meeting",
        content="",
        raw_metadata=json.dumps({"dtstart": soon, "dtend": ""}),
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    with patch("app.services.calendar_alerter.get_upcoming_events", return_value=[item]), \
         patch("app.services.calendar_alerter.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(event_alert_window_min=15)
        alerts = check_upcoming_alerts(session)

    assert len(alerts) == 1
    assert alerts[0]["external_id"] == "evt-1"
    assert alerts[0]["title"] == "Meeting"
    assert len(get_recent_alerts()) == 1
    persisted = session.exec(select(AlertedEvent)).all()
    assert len(persisted) == 1
    assert persisted[0].alert_key == f"evt-1|{soon}"


def test_check_upcoming_alerts_dedup() -> None:
    _recent_alerts.clear()
    session = _make_test_session()
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    item = SourceItem(
        source_type="calendar",
        external_id="evt-1",
        title="Meeting",
        content="",
        raw_metadata=json.dumps({"dtstart": soon, "dtend": ""}),
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    with patch("app.services.calendar_alerter.get_upcoming_events", return_value=[item]), \
         patch("app.services.calendar_alerter.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(event_alert_window_min=15)
        check_upcoming_alerts(session)
        alerts2 = check_upcoming_alerts(session)

    assert len(alerts2) == 0


def test_check_upcoming_alerts_no_events() -> None:
    _recent_alerts.clear()
    session = _make_test_session()

    with patch("app.services.calendar_alerter.get_upcoming_events", return_value=[]), \
         patch("app.services.calendar_alerter.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(event_alert_window_min=15)
        alerts = check_upcoming_alerts(session)

    assert len(alerts) == 0


def test_clear_stale_alert_keys() -> None:
    session = _make_test_session()
    old_dt = "2020-01-01T00:00:00+00:00"
    fresh_dt = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    session.add(AlertedEvent(alert_key=f"old-evt|{old_dt}", external_id="old-evt", dtstart=old_dt))
    session.add(AlertedEvent(alert_key=f"new-evt|{fresh_dt}", external_id="new-evt", dtstart=fresh_dt))
    session.commit()
    removed = clear_stale_alert_keys(session)
    assert removed == 1
    remaining = session.exec(select(AlertedEvent)).all()
    assert len(remaining) == 1
    assert remaining[0].external_id == "new-evt"


def test_get_recent_alerts_returns_list() -> None:
    _recent_alerts.clear()
    assert get_recent_alerts() == []
    assert isinstance(get_recent_alerts(), list)


def test_dedup_survives_new_session() -> None:
    """Dedup state persists across sessions (core bug D3.1 fix)."""
    _recent_alerts.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    item = SourceItem(
        source_type="calendar",
        external_id="evt-persist",
        title="Persist Test",
        content="",
        raw_metadata=json.dumps({"dtstart": soon, "dtend": ""}),
    )

    # Session 1: alert fires
    with Session(engine) as session1:
        session1.add(item)
        session1.commit()
        session1.refresh(item)
        with patch("app.services.calendar_alerter.get_upcoming_events", return_value=[item]), \
             patch("app.services.calendar_alerter.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(event_alert_window_min=15)
            alerts1 = check_upcoming_alerts(session1)
        assert len(alerts1) == 1

    # Session 2: same event should NOT re-alert (simulates process restart)
    with Session(engine) as session2:
        refreshed = session2.exec(select(SourceItem).where(SourceItem.external_id == "evt-persist")).first()
        with patch("app.services.calendar_alerter.get_upcoming_events", return_value=[refreshed]), \
             patch("app.services.calendar_alerter.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(event_alert_window_min=15)
            alerts2 = check_upcoming_alerts(session2)
        assert len(alerts2) == 0
