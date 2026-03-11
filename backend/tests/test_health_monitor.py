from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.scan_state import ScanState
from app.services.health_monitor import (
    _get_expected_interval_seconds,
    _is_source_stale,
    _should_alert,
    check_source_health,
    get_source_health_status,
)
import app.models  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _mock_settings(**overrides):
    s = MagicMock()
    s.calendar_scan_interval_min = 5
    s.email_scan_interval_min = 10
    s.notes_scan_interval_min = 30
    s.health_stale_multiplier = 3.0
    s.health_alert_cooldown_min = 60
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_get_expected_interval_seconds():
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _get_expected_interval_seconds("calendar") == 300
        assert _get_expected_interval_seconds("email") == 600
        assert _get_expected_interval_seconds("notes") == 1800
        assert _get_expected_interval_seconds("unknown") == 600


def test_is_source_stale_never_synced():
    state = ScanState(source_type="calendar", last_synced_at=None)
    now = datetime.now(timezone.utc)
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _is_source_stale(state, now) is True


def test_is_source_stale_recent_sync():
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="calendar", last_synced_at=now - timedelta(minutes=2))
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _is_source_stale(state, now) is False


def test_is_source_stale_old_sync():
    now = datetime.now(timezone.utc)
    # calendar interval = 5 min, multiplier = 3.0, threshold = 15 min
    state = ScanState(source_type="calendar", last_synced_at=now - timedelta(minutes=20))
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _is_source_stale(state, now) is True


def test_should_alert_never_alerted():
    state = ScanState(source_type="calendar", last_health_alert_at=None)
    now = datetime.now(timezone.utc)
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _should_alert(state, now) is True


def test_should_alert_recent_alert():
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="calendar", last_health_alert_at=now - timedelta(minutes=30))
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _should_alert(state, now) is False


def test_should_alert_old_alert():
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="calendar", last_health_alert_at=now - timedelta(minutes=90))
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        assert _should_alert(state, now) is True


def test_check_source_health_no_stale(db_session: Session):
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="calendar", status="idle", last_synced_at=now - timedelta(minutes=2))
    db_session.add(state)
    db_session.commit()
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        stale = check_source_health(db_session)
    assert len(stale) == 0


def test_check_source_health_stale_source(db_session: Session):
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="email", status="idle", last_synced_at=now - timedelta(minutes=60))
    db_session.add(state)
    db_session.commit()
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        stale = check_source_health(db_session)
    assert len(stale) == 1
    assert stale[0]["source_type"] == "email"


def test_check_source_health_skips_syncing(db_session: Session):
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="calendar", status="syncing", last_synced_at=now - timedelta(minutes=60))
    db_session.add(state)
    db_session.commit()
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        stale = check_source_health(db_session)
    assert len(stale) == 0


def test_check_source_health_respects_cooldown(db_session: Session):
    now = datetime.now(timezone.utc)
    state = ScanState(
        source_type="calendar",
        status="error",
        last_synced_at=now - timedelta(minutes=60),
        last_health_alert_at=now - timedelta(minutes=30),
    )
    db_session.add(state)
    db_session.commit()
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        stale = check_source_health(db_session)
    assert len(stale) == 0


def test_get_source_health_status(db_session: Session):
    now = datetime.now(timezone.utc)
    state = ScanState(source_type="notes", status="idle", last_synced_at=now - timedelta(minutes=2))
    db_session.add(state)
    db_session.commit()
    with patch("app.services.health_monitor.get_settings", return_value=_mock_settings()):
        result = get_source_health_status(db_session)
    assert len(result) == 1
    assert result[0]["source_type"] == "notes"
    assert result[0]["is_stale"] is False
    assert result[0]["elapsed_seconds"] is not None
