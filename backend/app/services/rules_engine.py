from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.models.notification_rule import NotificationRule
from app.models.notification_log import NotificationLog
from app.services.quiet_hours import is_in_quiet_hours, get_quiet_hours_config

logger = logging.getLogger(__name__)

PRIORITY_RANK: dict[str, int] = {"urgent": 0, "important": 1, "fyi": 2, "ignore": 3}

DEFAULT_RULES: list[dict[str, Any]] = [
    {"name": "Email notifications", "source_type": "email", "min_priority": "important", "enabled": True},
    {"name": "Calendar triage notifications", "source_type": "calendar", "min_priority": "important", "enabled": True},
    {"name": "Notes triage notifications", "source_type": "notes", "min_priority": "urgent", "enabled": True},
    {"name": "Calendar alert notifications", "source_type": "calendar_alert", "min_priority": "fyi", "enabled": True},
]


def ensure_default_rules(session: Session) -> int:
    count = 0
    for entry in DEFAULT_RULES:
        stmt = select(NotificationRule).where(NotificationRule.source_type == entry["source_type"])
        existing = session.exec(stmt).first()
        if existing is None:
            rule = NotificationRule(**entry)
            session.add(rule)
            count += 1
    session.commit()
    if count:
        logger.info("Created %d default notification rule(s)", count)
    return count


def get_rule_for_source(session: Session, source_type: str) -> NotificationRule | None:
    stmt = select(NotificationRule).where(NotificationRule.source_type == source_type)
    return session.exec(stmt).first()


def should_notify(session: Session, source_type: str, item_priority: str, external_id: str) -> str:
    rule = get_rule_for_source(session, source_type)
    if rule is None:
        return "no"
    if not rule.enabled:
        return "no"
    item_rank = PRIORITY_RANK.get(item_priority, 3)
    min_rank = PRIORITY_RANK.get(rule.min_priority, 0)
    if item_rank > min_rank:
        return "no"
    stmt = select(NotificationLog).where(
        NotificationLog.source_type == source_type,
        NotificationLog.external_id == external_id,
    )
    if session.exec(stmt).first() is not None:
        return "no"
    if is_in_quiet_hours(session):
        config = get_quiet_hours_config(session)
        if config is not None and config.bypass_urgent and item_priority == "urgent":
            return "yes"
        return "hold"
    return "yes"


def record_notification(
    session: Session,
    source_type: str,
    external_id: str,
    priority: str,
    title: str,
    rule_id: int | None = None,
    channel: str = "slack",
) -> NotificationLog:
    log_entry = NotificationLog(
        rule_id=rule_id,
        source_type=source_type,
        external_id=external_id,
        channel=channel,
        priority=priority,
        title=title,
    )
    session.add(log_entry)
    session.commit()
    session.refresh(log_entry)
    return log_entry


def get_all_rules(session: Session) -> list[NotificationRule]:
    stmt = select(NotificationRule).order_by(NotificationRule.source_type)
    return list(session.exec(stmt).all())


def update_rule(
    session: Session,
    rule_id: int,
    min_priority: str | None = None,
    enabled: bool | None = None,
) -> NotificationRule | None:
    rule = session.get(NotificationRule, rule_id)
    if rule is None:
        return None
    if min_priority is not None:
        if min_priority not in PRIORITY_RANK:
            raise ValueError(f"Invalid priority: {min_priority}. Must be one of: urgent, important, fyi, ignore")
        rule.min_priority = min_priority
    if enabled is not None:
        rule.enabled = enabled
    rule.updated_at = datetime.now(timezone.utc)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def get_notification_log(
    session: Session,
    source_type: str | None = None,
    limit: int = 50,
) -> list[NotificationLog]:
    stmt = select(NotificationLog)
    if source_type is not None:
        stmt = stmt.where(NotificationLog.source_type == source_type)
    stmt = stmt.order_by(NotificationLog.sent_at.desc()).limit(limit)
    return list(session.exec(stmt).all())
