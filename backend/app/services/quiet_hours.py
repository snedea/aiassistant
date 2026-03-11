from __future__ import annotations

import json
import logging
from datetime import datetime, time, UTC
from zoneinfo import ZoneInfo

from sqlmodel import Session, select, func

from app.database import get_engine
from app.models.quiet_hours import QuietHoursConfig
from app.models.held_notification import HeldNotification
from app.config import get_settings

logger = logging.getLogger(__name__)


def ensure_quiet_hours_config(session: Session) -> QuietHoursConfig:
    result = session.exec(select(QuietHoursConfig)).first()
    if result is not None:
        return result
    settings = get_settings()
    config = QuietHoursConfig(
        start_time=settings.quiet_hours_start if settings.quiet_hours_start else "22:00",
        end_time=settings.quiet_hours_end if settings.quiet_hours_end else "07:00",
        timezone="America/Chicago",
        enabled=bool(settings.quiet_hours_start and settings.quiet_hours_end),
        bypass_urgent=settings.quiet_hours_bypass_urgent,
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    logger.info("Created quiet hours config: %s-%s enabled=%s", config.start_time, config.end_time, config.enabled)
    return config


def get_quiet_hours_config(session: Session) -> QuietHoursConfig | None:
    return session.exec(select(QuietHoursConfig)).first()


def get_local_timezone() -> ZoneInfo:
    """Return the user's configured timezone from quiet hours config, or America/Chicago as fallback."""
    with Session(get_engine()) as session:
        config = get_quiet_hours_config(session)
        if config is not None and config.timezone:
            try:
                return ZoneInfo(config.timezone)
            except KeyError:
                logger.warning("Invalid timezone %r in quiet hours config, falling back to America/Chicago", config.timezone)
    return ZoneInfo("America/Chicago")


def update_quiet_hours_config(
    session: Session,
    start_time: str | None = None,
    end_time: str | None = None,
    tz: str | None = None,
    enabled: bool | None = None,
    bypass_urgent: bool | None = None,
) -> QuietHoursConfig | None:
    config = get_quiet_hours_config(session)
    if config is None:
        return None
    if start_time is not None:
        _parse_time(start_time)
        config.start_time = start_time
    if end_time is not None:
        _parse_time(end_time)
        config.end_time = end_time
    if tz is not None:
        try:
            ZoneInfo(tz)
        except (KeyError, Exception):
            raise ValueError(f"Invalid timezone: {tz!r}. Must be a valid IANA timezone (e.g. 'America/New_York', 'Europe/London').")
        config.timezone = tz
    if enabled is not None:
        config.enabled = enabled
    if bypass_urgent is not None:
        config.bypass_urgent = bypass_urgent
    config.updated_at = datetime.now(UTC)
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


def _parse_time(time_str: str) -> time:
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}. Use HH:MM format.")
    hour = int(parts[0])
    minute = int(parts[1])
    return time(hour, minute)


def is_in_quiet_hours(session: Session) -> bool:
    config = get_quiet_hours_config(session)
    if config is None or not config.enabled:
        return False
    try:
        start = _parse_time(config.start_time)
        end = _parse_time(config.end_time)
    except ValueError:
        logger.warning("Invalid quiet hours time format: %s-%s", config.start_time, config.end_time)
        return False
    now_utc = datetime.now(UTC)
    try:
        local_tz = ZoneInfo(config.timezone)
    except KeyError:
        logger.warning("Unknown timezone '%s', falling back to America/Chicago", config.timezone)
        local_tz = ZoneInfo("America/Chicago")
    now_local = now_utc.astimezone(local_tz).time()
    if start <= end:
        return start <= now_local < end
    return now_local >= start or now_local < end


def hold_notification(
    session: Session,
    source_type: str,
    external_id: str,
    priority: str,
    title: str,
    channel: str,
    payload: dict,
    notification_type: str,
    rule_id: int | None = None,
) -> HeldNotification:
    held = HeldNotification(
        source_type=source_type,
        external_id=external_id,
        priority=priority,
        title=title,
        channel=channel,
        payload_json=json.dumps(payload),
        notification_type=notification_type,
        rule_id=rule_id,
    )
    session.add(held)
    session.commit()
    session.refresh(held)
    logger.info("Held notification during quiet hours: [%s] %s", source_type, title)
    return held


def get_held_notifications(session: Session) -> list[HeldNotification]:
    stmt = select(HeldNotification).order_by(HeldNotification.created_at.asc())
    return list(session.exec(stmt).all())


def delete_held_notification(session: Session, held_id: int) -> None:
    held = session.get(HeldNotification, held_id)
    if held is not None:
        session.delete(held)
        session.commit()


def increment_flush_attempts(session: Session, held_id: int) -> None:
    held = session.get(HeldNotification, held_id)
    if held is None:
        return
    held.flush_attempts = held.flush_attempts + 1
    session.add(held)
    session.commit()


def count_held_notifications(session: Session) -> int:
    stmt = select(func.count()).select_from(HeldNotification)
    result = session.exec(stmt).one()
    return result
