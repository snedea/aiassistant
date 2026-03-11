from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Any

import caldav
from icalendar import Calendar as ICalendar
from sqlmodel import Session, select

from app.config import get_settings
from app.models.source_item import SourceItem
from app.models.scan_state import ScanState

logger = logging.getLogger(__name__)


def _get_caldav_client() -> caldav.DAVClient:
    settings = get_settings()
    if settings.caldav_url == "":
        raise ValueError("CALDAV_URL is not configured")
    return caldav.DAVClient(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
    )


def _parse_vevent(vevent: Any) -> dict[str, Any] | None:
    try:
        uid = vevent.get("UID")
        if uid is None:
            return None
        uid = str(uid)

        summary = str(vevent.get("SUMMARY", ""))
        description = str(vevent.get("DESCRIPTION", ""))
        location = str(vevent.get("LOCATION", ""))

        dtstart_prop = vevent.get("DTSTART")
        if dtstart_prop is not None:
            dtstart = dtstart_prop.dt
        else:
            dtstart = None

        dtend_prop = vevent.get("DTEND")
        if dtend_prop is not None:
            dtend = dtend_prop.dt
        else:
            dtend = None

        if dtstart is not None:
            if isinstance(dtstart, datetime):
                dtstart_str = dtstart.astimezone(timezone.utc).isoformat()
            else:
                dtstart_str = dtstart.isoformat() + " (all-day)"
        else:
            dtstart_str = ""

        if dtend is not None:
            if isinstance(dtend, datetime):
                dtend_str = dtend.astimezone(timezone.utc).isoformat()
            else:
                dtend_str = dtend.isoformat() + " (all-day)"
        else:
            dtend_str = ""

        attendees_prop = vevent.get("ATTENDEE")
        if attendees_prop is not None and isinstance(attendees_prop, list):
            attendees = [str(a) for a in attendees_prop]
        elif attendees_prop is not None:
            attendees = [str(attendees_prop)]
        else:
            attendees = []

        status = str(vevent.get("STATUS", ""))

        rrule_val = vevent.get("RRULE")
        rrule = str(rrule_val) if rrule_val is not None else ""

        return {
            "uid": uid,
            "summary": summary,
            "description": description,
            "location": location,
            "dtstart": dtstart_str,
            "dtend": dtend_str,
            "attendees": attendees,
            "status": status,
            "rrule": rrule,
        }
    except Exception:
        logger.warning("Failed to parse VEVENT", exc_info=True)
        return None


def fetch_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    client = _get_caldav_client()
    principal = client.principal()
    calendars = principal.calendars()

    events: list[dict[str, Any]] = []
    for cal in calendars:
        try:
            results = cal.search(start=start, end=end, event=True, expand=True)
        except Exception:
            logger.warning("Failed to search calendar %s", cal, exc_info=True)
            continue
        for event_result in results:
            ical_data = event_result.data
            parsed = ICalendar.from_ical(ical_data)
            for component in parsed.walk("VEVENT"):
                result = _parse_vevent(component)
                if result is not None:
                    events.append(result)
    return events


def _parse_dtstart_utc(dtstart_str: str) -> datetime | None:
    if not dtstart_str or dtstart_str.endswith("(all-day)"):
        return None
    try:
        return datetime.fromisoformat(dtstart_str)
    except ValueError:
        return None


def sync_calendar_events(session: Session, days_ahead: int = 7, days_behind: int = 1) -> tuple[int, list[int]]:
    statement = select(ScanState).where(ScanState.source_type == "calendar")
    scan_state = session.exec(statement).first()
    if scan_state is None:
        scan_state = ScanState(source_type="calendar", status="idle")
        session.add(scan_state)

    scan_state.status = "syncing"
    scan_state.error_message = None
    session.commit()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_behind)
    end = now + timedelta(days=days_ahead)

    try:
        events = fetch_events(start, end)
        synced_count = 0
        new_items: list[SourceItem] = []
        updated_items: list[SourceItem] = []

        for event_data in events:
            external_id = event_data["uid"]
            stmt = select(SourceItem).where(
                SourceItem.source_type == "calendar",
                SourceItem.external_id == external_id,
            )
            existing = session.exec(stmt).first()

            metadata_dict = {
                "dtstart": event_data["dtstart"],
                "dtend": event_data["dtend"],
                "location": event_data["location"],
                "attendees": event_data["attendees"],
                "status": event_data["status"],
                "rrule": event_data["rrule"],
            }
            metadata_json = json.dumps(metadata_dict)
            new_hash = SourceItem.compute_hash(event_data["summary"], event_data["description"], metadata_json)

            if existing is not None:
                if existing.content_hash == new_hash:
                    synced_count += 1
                    continue
                existing.title = event_data["summary"]
                existing.content = event_data["description"]
                existing.raw_metadata = metadata_json
                existing.updated_at = datetime.now(timezone.utc)
                existing.content_hash = new_hash
                existing.dtstart_utc = _parse_dtstart_utc(event_data["dtstart"])
                existing.embedded = False
                session.add(existing)
                updated_items.append(existing)
            else:
                parsed_dtstart_utc = _parse_dtstart_utc(event_data["dtstart"])
                item = SourceItem(
                    source_type="calendar",
                    external_id=external_id,
                    title=event_data["summary"],
                    content=event_data["description"],
                    raw_metadata=metadata_json,
                    content_hash=new_hash,
                    dtstart_utc=parsed_dtstart_utc,
                )
                session.add(item)
                new_items.append(item)

            synced_count += 1

        session.commit()
        changed_ids = [item.id for item in new_items] + [item.id for item in updated_items]

        scan_state.status = "idle"
        scan_state.last_synced_at = datetime.now(timezone.utc)
        scan_state.items_synced = synced_count
        session.commit()

        logger.info("Calendar sync complete: %d events synced, %d changed", synced_count, len(changed_ids))
        return (synced_count, changed_ids)

    except Exception as e:
        scan_state.status = "error"
        scan_state.error_message = str(e)[:500]
        session.commit()
        logger.error("Calendar sync failed: %s", e, exc_info=True)
        raise


def get_upcoming_events(session: Session, within_minutes: int = 15) -> list[SourceItem]:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(minutes=within_minutes)
    stmt = (
        select(SourceItem)
        .where(
            SourceItem.source_type == "calendar",
            SourceItem.dtstart_utc.is_not(None),  # type: ignore[union-attr]
            SourceItem.dtstart_utc >= now,  # type: ignore[operator]
            SourceItem.dtstart_utc <= cutoff,  # type: ignore[operator]
        )
        .order_by(SourceItem.dtstart_utc)
    )
    return list(session.exec(stmt).all())
