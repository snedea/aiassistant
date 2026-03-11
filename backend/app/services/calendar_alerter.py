from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select, delete, func

from app.adapters.calendar import get_upcoming_events
from app.config import get_settings
from app.database import get_engine
from app.models.alerted_event import AlertedEvent
from app.notifications.slack import notify_calendar_alert
from app.notifications.imessage import notify_calendar_alert_imessage
from app.services.rules_engine import should_notify, record_notification, get_rule_for_source
from app.services.quiet_hours import hold_notification

logger = logging.getLogger(__name__)

_recent_alerts: deque[dict[str, Any]] = deque(maxlen=50)


def _event_alert_key(event_external_id: str, dtstart: str) -> str:
    return f"{event_external_id}|{dtstart}"


def _is_already_alerted(session: Session, key: str) -> bool:
    result = session.exec(select(AlertedEvent).where(AlertedEvent.alert_key == key)).first()
    return result is not None


def _record_alert(session: Session, key: str, external_id: str, dtstart: str) -> None:
    record = AlertedEvent(alert_key=key, external_id=external_id, dtstart=dtstart)
    session.add(record)
    session.commit()


def check_upcoming_alerts(session: Session, within_minutes: int | None = None) -> list[dict[str, Any]]:
    if within_minutes is None:
        within_minutes = get_settings().event_alert_window_min
    events = get_upcoming_events(session, within_minutes=within_minutes)
    new_alerts: list[dict[str, Any]] = []
    for event in events:
        try:
            metadata = json.loads(event.raw_metadata)
            dtstart = metadata.get("dtstart", "")
            key = _event_alert_key(event.external_id, dtstart)
            if _is_already_alerted(session, key):
                continue
            _record_alert(session, key, event.external_id, dtstart)
            alert = {
                "event_id": event.id,
                "external_id": event.external_id,
                "title": event.title,
                "dtstart": dtstart,
                "dtend": metadata.get("dtend", ""),
                "location": metadata.get("location", ""),
                "alerted_at": datetime.now(timezone.utc).isoformat(),
            }
            new_alerts.append(alert)
            _recent_alerts.append(alert)
            logger.info("Calendar alert: '%s' starts at %s", event.title, dtstart)
        except Exception:
            logger.warning("Skipping event %s: bad metadata", event.id)
            continue
    return new_alerts


def get_recent_alerts() -> list[dict[str, Any]]:
    return list(_recent_alerts)


def clear_stale_alert_keys(session: Session) -> int:
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    count_stmt = select(func.count()).select_from(AlertedEvent).where(
        AlertedEvent.dtstart <= cutoff_iso
    )
    removed = session.exec(count_stmt).one()
    if removed > 0:
        del_stmt = delete(AlertedEvent).where(AlertedEvent.dtstart <= cutoff_iso)
        session.exec(del_stmt)
        session.commit()
    return removed


async def run_calendar_alert_loop(interval_seconds: int) -> None:
    logger.info("Calendar alert loop started (interval=%ds)", interval_seconds)
    while True:
        try:
            with Session(get_engine()) as session:
                new_alerts = check_upcoming_alerts(session)
                if len(new_alerts) > 0:
                    logger.info("Calendar alert loop: %d new alert(s)", len(new_alerts))
                    rule = get_rule_for_source(session, "calendar_alert")
                    for alert in new_alerts:
                        alert_key = f"{alert['external_id']}|{alert['dtstart']}"
                        notify_decision = should_notify(session, "calendar_alert", "urgent", alert_key)
                        if notify_decision == "hold":
                            hold_notification(
                                session, "calendar_alert", alert_key, "urgent",
                                alert.get("title", ""), "slack", alert, "calendar_alert",
                                rule_id=rule.id if rule else None,
                            )
                        elif notify_decision == "yes":
                            sent = await notify_calendar_alert(alert)
                            await notify_calendar_alert_imessage(alert)
                            if sent:
                                record_notification(
                                    session, "calendar_alert", alert_key,
                                    "urgent", alert.get("title", ""),
                                    rule_id=rule.id if rule else None,
                                )
                removed = clear_stale_alert_keys(session)
                if removed > 0:
                    logger.debug("Cleared %d stale alert keys", removed)
        except Exception as e:
            logger.error("Calendar alert loop failed: %s", e, exc_info=True)
        await asyncio.sleep(interval_seconds)
