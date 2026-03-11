from __future__ import annotations

import asyncio
import json
import logging

from sqlmodel import Session

from app.database import get_engine
from app.notifications.slack import notify_calendar_alert, notify_triage_results, notify_email_summaries
from app.notifications.imessage import notify_calendar_alert_imessage, notify_triage_results_imessage, notify_email_summaries_imessage
from app.services.quiet_hours import is_in_quiet_hours, get_held_notifications, delete_held_notification, count_held_notifications, increment_flush_attempts
from app.services.rules_engine import record_notification

logger = logging.getLogger(__name__)

MAX_FLUSH_ATTEMPTS = 10


async def flush_held_notifications(session: Session) -> int:
    held_list = get_held_notifications(session)
    if not held_list:
        return 0
    sent = 0
    for held in held_list:
        if held.flush_attempts >= MAX_FLUSH_ATTEMPTS:
            logger.warning("Held notification %d exceeded max flush attempts (%d), discarding: [%s] %s", held.id, MAX_FLUSH_ATTEMPTS, held.source_type, held.title)
            delete_held_notification(session, held.id)
            continue
        success = False
        try:
            payload = json.loads(held.payload_json)
            if held.notification_type == "email":
                result = await notify_email_summaries([payload], min_importance="ignore")
                success = result > 0
                try:
                    await notify_email_summaries_imessage([payload], min_importance="ignore")
                except Exception as e:
                    logger.warning("iMessage delivery failed for held notification %d (email): %s", held.id, e)
            elif held.notification_type == "triage":
                result = await notify_triage_results([payload], min_priority="ignore")
                success = result > 0
                try:
                    await notify_triage_results_imessage([payload], min_priority="ignore")
                except Exception as e:
                    logger.warning("iMessage delivery failed for held notification %d (triage): %s", held.id, e)
            elif held.notification_type == "calendar_alert":
                success = await notify_calendar_alert(payload)
                try:
                    await notify_calendar_alert_imessage(payload)
                except Exception as e:
                    logger.warning("iMessage delivery failed for held notification %d (calendar_alert): %s", held.id, e)
        except Exception as e:
            logger.error("Failed to flush held notification %d: %s", held.id, e, exc_info=True)
        if success:
            record_notification(session, held.source_type, held.external_id, held.priority, held.title, rule_id=held.rule_id, channel=held.channel)
            delete_held_notification(session, held.id)
            sent += 1
        else:
            increment_flush_attempts(session, held.id)
            logger.warning("Held notification %d delivery failed (attempt %d/%d): [%s] %s", held.id, held.flush_attempts, MAX_FLUSH_ATTEMPTS, held.source_type, held.title)
    if sent > 0:
        logger.info("Flushed %d held notification(s) after quiet hours ended", sent)
    return sent


async def run_quiet_hours_flush_loop(interval_seconds: int = 60) -> None:
    logger.info("Quiet hours flush loop started (interval=%ds)", interval_seconds)
    was_in_quiet_hours = False
    while True:
        try:
            with Session(get_engine()) as session:
                currently_quiet = is_in_quiet_hours(session)
                if was_in_quiet_hours and not currently_quiet:
                    logger.info("Quiet hours ended, flushing held notifications")
                    await flush_held_notifications(session)
                if not currently_quiet and count_held_notifications(session) > 0:
                    logger.info("Found held notifications outside quiet hours, flushing")
                    await flush_held_notifications(session)
                was_in_quiet_hours = currently_quiet
        except Exception as e:
            logger.error("Quiet hours flush loop failed: %s", e, exc_info=True)
        await asyncio.sleep(interval_seconds)
