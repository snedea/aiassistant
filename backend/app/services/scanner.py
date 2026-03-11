from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.database import get_engine
from app.models.source_item import SourceItem
from app.adapters.calendar import sync_calendar_events
from app.adapters.notes import sync_notes
from app.adapters.email import sync_emails
from app.services.embedding import embed_source_items
from app.services.email_summarizer import summarize_new_emails
from app.services.triage_service import triage_items
from app.config import get_settings
from app.services.calendar_alerter import run_calendar_alert_loop
from app.notifications.slack import notify_calendar_alert, notify_triage_results, notify_email_summaries
from app.notifications.imessage import notify_calendar_alert_imessage, notify_triage_results_imessage, notify_email_summaries_imessage
from app.services.rules_engine import should_notify, record_notification, get_rule_for_source
from app.services.quiet_hours import hold_notification
from app.services.quiet_hours_flusher import run_quiet_hours_flush_loop
from app.services.daily_digest import run_daily_digest_loop
from app.services.health_monitor import run_health_monitor_loop
from app.services.llm_rate_limiter import BudgetExceededError

logger = logging.getLogger(__name__)


async def _run_source_sync(source_name: str, sync_fn: callable, sync_kwargs: dict, interval_seconds: int) -> None:
    logger.info("Scanner loop started for %s (interval=%ds)", source_name, interval_seconds)
    while True:
        try:
            with Session(get_engine()) as session:
                synced_count, changed_ids = await asyncio.to_thread(sync_fn, session, **sync_kwargs)
                # Embed all unembedded items (newly synced + previously failed)
                unembedded_stmt = select(SourceItem.id).where(
                    SourceItem.source_type == source_name,
                    SourceItem.embedded == False,
                )
                unembedded_ids = list(session.exec(unembedded_stmt).all())
                if unembedded_ids:
                    try:
                        await embed_source_items(session, item_ids=unembedded_ids)
                        for item_id in unembedded_ids:
                            item = session.get(SourceItem, item_id)
                            if item is not None:
                                item.embedded = True
                                session.add(item)
                        session.commit()
                        logger.info("Scanner: embedded %d items for %s", len(unembedded_ids), source_name)
                    except Exception as embed_err:
                        logger.warning("Scanner: embedding failed for %s, %d items remain unembedded: %s", source_name, len(unembedded_ids), embed_err)
                        session.rollback()
                if changed_ids and source_name == "email":
                    try:
                        summaries = await summarize_new_emails(session, changed_ids)
                        if summaries:
                            logger.info("Scanner: email summarizer produced %d summaries", len(summaries))
                            rule = get_rule_for_source(session, "email")
                            sent = 0
                            for s in summaries:
                                summary_dict = {
                                    "importance": s.importance,
                                    "subject": s.subject,
                                    "summary": s.summary,
                                    "from": s.from_addr,
                                }
                                notify_decision = should_notify(session, "email", s.importance, s.external_id)
                                if notify_decision == "hold":
                                    hold_notification(
                                        session, "email", s.external_id, s.importance, s.subject, "slack",
                                        summary_dict, "email", rule_id=rule.id if rule else None,
                                    )
                                elif notify_decision == "yes":
                                    result = await notify_email_summaries([summary_dict], min_importance="ignore")
                                    await notify_email_summaries_imessage([summary_dict], min_importance="ignore")
                                    if result > 0:
                                        record_notification(session, "email", s.external_id, s.importance, s.subject, rule_id=rule.id if rule else None)
                                        sent += 1
                            if sent:
                                logger.info("Scanner: sent %d Slack notification(s) for email summaries", sent)
                    except BudgetExceededError:
                        logger.info("Scanner: email summarizer skipped (daily token budget exhausted)")
                    except Exception as e:
                        logger.error("Scanner: email summarizer failed: %s", e, exc_info=True)
                if changed_ids and source_name in ("calendar", "notes"):
                    try:
                        triages = await triage_items(session, changed_ids, source_name)
                        if triages:
                            logger.info("Scanner: triage produced %d results for %s", len(triages), source_name)
                            rule = get_rule_for_source(session, source_name)
                            sent = 0
                            for t in triages:
                                triage_dict = {
                                    "source_type": t.source_type,
                                    "title": t.title,
                                    "priority": t.priority,
                                    "summary": t.summary,
                                }
                                notify_decision = should_notify(session, source_name, t.priority, t.external_id)
                                if notify_decision == "hold":
                                    hold_notification(
                                        session, source_name, t.external_id, t.priority, t.title, "slack",
                                        triage_dict, "triage", rule_id=rule.id if rule else None,
                                    )
                                elif notify_decision == "yes":
                                    result = await notify_triage_results([triage_dict], min_priority="ignore")
                                    await notify_triage_results_imessage([triage_dict], min_priority="ignore")
                                    if result > 0:
                                        record_notification(session, source_name, t.external_id, t.priority, t.title, rule_id=rule.id if rule else None)
                                        sent += 1
                            if sent:
                                logger.info("Scanner: sent %d Slack notification(s) for %s triage", sent, source_name)
                    except BudgetExceededError:
                        logger.info("Scanner: triage skipped for %s (daily token budget exhausted)", source_name)
                    except Exception as e:
                        logger.error("Scanner: triage failed for %s: %s", source_name, e, exc_info=True)
                logger.info("Scanner: %s sync complete -- %d synced, %d changed", source_name, synced_count, len(changed_ids))
        except Exception as e:
            logger.error("Scanner: %s sync failed: %s", source_name, e, exc_info=True)
        await asyncio.sleep(interval_seconds)


async def start_scanner() -> list[asyncio.Task]:
    settings = get_settings()
    tasks: list[asyncio.Task] = []
    sources = [
        {
            "name": "calendar",
            "sync_fn": sync_calendar_events,
            "sync_kwargs": {},
            "interval_seconds": settings.calendar_scan_interval_min * 60,
            "enabled": settings.caldav_url != "",
        },
        {
            "name": "email",
            "sync_fn": sync_emails,
            "sync_kwargs": {},
            "interval_seconds": settings.email_scan_interval_min * 60,
            "enabled": settings.imap_host != "",
        },
        {
            "name": "notes",
            "sync_fn": sync_notes,
            "sync_kwargs": {},
            "interval_seconds": settings.notes_scan_interval_min * 60,
            "enabled": True,
        },
    ]
    for source in sources:
        if not source["enabled"]:
            logger.info("Scanner: %s disabled (not configured)", source["name"])
            continue
        task = asyncio.create_task(
            _run_source_sync(source["name"], source["sync_fn"], source["sync_kwargs"], source["interval_seconds"]),
            name=f"scanner-{source['name']}",
        )
        tasks.append(task)
    # Calendar alert scanner (checks for events starting soon)
    if settings.caldav_url.strip() != "":
        alert_task = asyncio.create_task(
            run_calendar_alert_loop(settings.calendar_scan_interval_min * 60),
            name="scanner-calendar-alerts",
        )
        tasks.append(alert_task)
    # Quiet hours flush loop (checks every 60s if quiet hours ended)
    flush_task = asyncio.create_task(
        run_quiet_hours_flush_loop(interval_seconds=60),
        name="scanner-quiet-hours-flush",
    )
    tasks.append(flush_task)
    # Daily digest loop (checks every 60s if it's time to send the morning digest)
    if settings.digest_enabled:
        digest_task = asyncio.create_task(
            run_daily_digest_loop(),
            name="scanner-daily-digest",
        )
        tasks.append(digest_task)
    # Health monitor loop (checks if sources have stopped syncing)
    health_task = asyncio.create_task(
        run_health_monitor_loop(interval_seconds=settings.health_check_interval_min * 60),
        name="scanner-health-monitor",
    )
    tasks.append(health_task)
    if len(tasks) > 0:
        logger.info("Scanner started with %d source(s)", len(tasks))
    else:
        logger.info("Scanner: no sources configured, nothing to scan")
    return tasks


async def stop_scanner(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Scanner stopped (%d tasks cancelled)", len(tasks))
