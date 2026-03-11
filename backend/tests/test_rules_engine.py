from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.models.notification_rule import NotificationRule
from app.models.notification_log import NotificationLog
from app.models.quiet_hours import QuietHoursConfig  # noqa: F401
from app.models.held_notification import HeldNotification  # noqa: F401
from app.services.rules_engine import (
    ensure_default_rules,
    get_rule_for_source,
    should_notify,
    record_notification,
    get_all_rules,
    update_rule,
    get_notification_log,
    DEFAULT_RULES,
    PRIORITY_RANK,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_ensure_default_rules_creates_all(session: Session) -> None:
    count = ensure_default_rules(session)
    assert count == len(DEFAULT_RULES)
    rules = get_all_rules(session)
    assert len(rules) == len(DEFAULT_RULES)
    assert {r.source_type for r in rules} == {"email", "calendar", "notes", "calendar_alert"}


def test_ensure_default_rules_idempotent(session: Session) -> None:
    ensure_default_rules(session)
    count = ensure_default_rules(session)
    assert count == 0
    rules = get_all_rules(session)
    assert len(rules) == len(DEFAULT_RULES)


def test_get_rule_for_source(session: Session) -> None:
    ensure_default_rules(session)
    rule = get_rule_for_source(session, "email")
    assert rule is not None
    assert rule.source_type == "email"
    assert rule.min_priority == "important"
    missing = get_rule_for_source(session, "nonexistent")
    assert missing is None


def test_should_notify_passes_above_threshold(session: Session) -> None:
    ensure_default_rules(session)
    assert should_notify(session, "email", "urgent", "ext-1") == "yes"
    assert should_notify(session, "email", "important", "ext-2") == "yes"


def test_should_notify_blocks_below_threshold(session: Session) -> None:
    ensure_default_rules(session)
    assert should_notify(session, "email", "fyi", "ext-3") == "no"
    assert should_notify(session, "email", "ignore", "ext-4") == "no"


def test_should_notify_blocks_disabled_rule(session: Session) -> None:
    ensure_default_rules(session)
    rule = get_rule_for_source(session, "email")
    update_rule(session, rule.id, enabled=False)
    assert should_notify(session, "email", "urgent", "ext-5") == "no"


def test_should_notify_dedup(session: Session) -> None:
    ensure_default_rules(session)
    assert should_notify(session, "email", "urgent", "ext-dup") == "yes"
    record_notification(session, "email", "ext-dup", "urgent", "Test")
    assert should_notify(session, "email", "urgent", "ext-dup") == "no"


def test_update_rule_changes_priority(session: Session) -> None:
    ensure_default_rules(session)
    rule = get_rule_for_source(session, "email")
    updated = update_rule(session, rule.id, min_priority="fyi")
    assert updated.min_priority == "fyi"
    assert should_notify(session, "email", "fyi", "ext-fyi") == "yes"


def test_update_rule_invalid_priority(session: Session) -> None:
    ensure_default_rules(session)
    rule = get_rule_for_source(session, "email")
    with pytest.raises(ValueError):
        update_rule(session, rule.id, min_priority="bogus")


def test_update_rule_not_found(session: Session) -> None:
    result = update_rule(session, 999, min_priority="urgent")
    assert result is None


def test_record_and_get_notification_log(session: Session) -> None:
    record_notification(session, "email", "ext-log-1", "urgent", "Server Down")
    record_notification(session, "calendar", "ext-log-2", "important", "Meeting")
    all_logs = get_notification_log(session)
    assert len(all_logs) == 2
    email_logs = get_notification_log(session, source_type="email")
    assert len(email_logs) == 1
    assert email_logs[0].title == "Server Down"


def test_should_notify_no_rule_returns_false(session: Session) -> None:
    assert should_notify(session, "email", "urgent", "ext-no-rule") == "no"
