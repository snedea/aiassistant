from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlmodel import Session, select

from app.database import get_engine
from app.config import get_settings
from app.models.scan_state import ScanState
from app.notifications.slack import send_slack_webhook
from app.notifications.imessage import send_imessage

logger = logging.getLogger(__name__)


def _get_expected_interval_seconds(source_type: str) -> int:
    settings = get_settings()
    if source_type == "calendar":
        return settings.calendar_scan_interval_min * 60
    if source_type == "email":
        return settings.email_scan_interval_min * 60
    if source_type == "notes":
        return settings.notes_scan_interval_min * 60
    return 600


def _is_source_stale(scan_state: ScanState, now: datetime) -> bool:
    if scan_state.last_synced_at is None:
        return True
    interval_seconds = _get_expected_interval_seconds(scan_state.source_type)
    settings = get_settings()
    threshold_seconds = interval_seconds * settings.health_stale_multiplier
    last_synced = scan_state.last_synced_at
    if last_synced.tzinfo is None:
        last_synced = last_synced.replace(tzinfo=timezone.utc)
    elapsed = (now - last_synced).total_seconds()
    return elapsed > threshold_seconds


def _should_alert(scan_state: ScanState, now: datetime) -> bool:
    if scan_state.last_health_alert_at is None:
        return True
    settings = get_settings()
    cooldown = timedelta(minutes=settings.health_alert_cooldown_min)
    last_alert = scan_state.last_health_alert_at
    if last_alert.tzinfo is None:
        last_alert = last_alert.replace(tzinfo=timezone.utc)
    return (now - last_alert) > cooldown


def _build_stale_alert_blocks(source_type: str, last_synced_at: datetime | None, expected_interval_min: int) -> list[dict]:
    if last_synced_at is not None:
        elapsed_min = int((datetime.now(timezone.utc) - last_synced_at).total_seconds() / 60)
        last_sync_text = f"{elapsed_min} minutes ago"
    else:
        last_sync_text = "never"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": ":warning: Source stale: " + source_type}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Source:* {source_type}\n*Last synced:* {last_sync_text}\n*Expected interval:* every {expected_interval_min} min"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Health monitor alert from AI Assistant"}]},
    ]


def check_source_health(session: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    scan_states = session.exec(select(ScanState)).all()
    stale_sources: list[dict] = []
    for scan_state in scan_states:
        if scan_state.status == "syncing":
            continue
        if not _is_source_stale(scan_state, now):
            continue
        if not _should_alert(scan_state, now):
            continue
        expected_interval_min = _get_expected_interval_seconds(scan_state.source_type) // 60
        stale_sources.append({
            "source_type": scan_state.source_type,
            "last_synced_at": scan_state.last_synced_at,
            "status": scan_state.status,
            "error_message": scan_state.error_message,
            "expected_interval_min": expected_interval_min,
        })
        scan_state.last_health_alert_at = now
    if len(stale_sources) > 0:
        session.commit()
    return stale_sources


async def _send_health_alerts(stale_sources: list[dict]) -> int:
    sent = 0
    for source in stale_sources:
        blocks = _build_stale_alert_blocks(source["source_type"], source["last_synced_at"], source["expected_interval_min"])
        fallback_text = f"Source health alert: {source['source_type']} has not synced (last: {source['last_synced_at'] or 'never'})"
        if await send_slack_webhook(text=fallback_text, blocks=blocks):
            sent += 1
        imessage_text = f"[HEALTH] Source '{source['source_type']}' stopped syncing. Last sync: {source['last_synced_at'] or 'never'}. Expected every {source['expected_interval_min']}min."
        await send_imessage(imessage_text)
    return sent


async def run_health_monitor_loop(interval_seconds: int) -> None:
    logger.info("Health monitor started (interval=%ds)", interval_seconds)
    while True:
        try:
            with Session(get_engine()) as session:
                stale_sources = check_source_health(session)
                if stale_sources:
                    logger.warning("Health monitor: %d source(s) stale: %s", len(stale_sources), [s["source_type"] for s in stale_sources])
                    sent = await _send_health_alerts(stale_sources)
                    logger.info("Health monitor: sent %d alert(s)", sent)
        except Exception as e:
            logger.error("Health monitor check failed: %s", e, exc_info=True)
        await asyncio.sleep(interval_seconds)


def get_source_health_status(session: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    scan_states = session.exec(select(ScanState)).all()
    result: list[dict] = []
    for scan_state in scan_states:
        is_stale = _is_source_stale(scan_state, now)
        expected_interval_min = _get_expected_interval_seconds(scan_state.source_type) // 60
        if scan_state.last_synced_at is not None:
            last_synced = scan_state.last_synced_at
            if last_synced.tzinfo is None:
                last_synced = last_synced.replace(tzinfo=timezone.utc)
            elapsed_seconds = int((now - last_synced).total_seconds())
        else:
            elapsed_seconds = None
        result.append({
            "source_type": scan_state.source_type,
            "is_stale": is_stale,
            "last_synced_at": scan_state.last_synced_at.isoformat() if scan_state.last_synced_at else None,
            "elapsed_seconds": elapsed_seconds,
            "expected_interval_min": expected_interval_min,
            "status": scan_state.status,
            "error_message": scan_state.error_message,
            "last_health_alert_at": scan_state.last_health_alert_at.isoformat() if scan_state.last_health_alert_at else None,
        })
    return result
