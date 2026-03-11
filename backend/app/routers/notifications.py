from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import require_auth
from app.config import get_settings
from app.database import get_session
from app.services.rules_engine import get_all_rules, update_rule, get_notification_log
from app.services.quiet_hours import get_quiet_hours_config, update_quiet_hours_config, is_in_quiet_hours, get_held_notifications, count_held_notifications
from app.services.daily_digest import generate_and_send_digest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class RuleUpdateRequest(BaseModel):
    min_priority: str | None = None
    enabled: bool | None = None


class QuietHoursUpdateRequest(BaseModel):
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    bypass_urgent: bool | None = None


@router.get("/rules")
async def list_rules(session: Session = Depends(get_session)) -> dict:
    rules = get_all_rules(session)
    response_list = [
        {
            "id": r.id,
            "name": r.name,
            "source_type": r.source_type,
            "min_priority": r.min_priority,
            "enabled": r.enabled,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rules
    ]
    return {"rules": response_list, "count": len(response_list)}


@router.put("/rules/{rule_id}")
async def update_rule_endpoint(rule_id: int, body: RuleUpdateRequest, session: Session = Depends(get_session)) -> dict:
    if body.min_priority is None and body.enabled is None:
        raise HTTPException(status_code=400, detail="Provide at least one of: min_priority, enabled")
    try:
        rule = update_rule(session, rule_id, min_priority=body.min_priority, enabled=body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {
        "status": "updated",
        "rule": {
            "id": rule.id,
            "name": rule.name,
            "source_type": rule.source_type,
            "min_priority": rule.min_priority,
            "enabled": rule.enabled,
            "updated_at": rule.updated_at.isoformat(),
        },
    }


@router.get("/log")
async def list_notification_log(
    source_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    logs = get_notification_log(session, source_type=source_type, limit=limit)
    response_list = [
        {
            "id": entry.id,
            "rule_id": entry.rule_id,
            "source_type": entry.source_type,
            "external_id": entry.external_id,
            "channel": entry.channel,
            "priority": entry.priority,
            "title": entry.title,
            "sent_at": entry.sent_at.isoformat(),
        }
        for entry in logs
    ]
    return {"log": response_list, "count": len(response_list)}


@router.get("/quiet-hours")
async def get_quiet_hours(session: Session = Depends(get_session)) -> dict:
    config = get_quiet_hours_config(session)
    if config is None:
        return {"config": None, "currently_active": False, "held_count": 0}
    active = is_in_quiet_hours(session)
    held = count_held_notifications(session)
    return {
        "config": {
            "id": config.id,
            "start_time": config.start_time,
            "end_time": config.end_time,
            "timezone": config.timezone,
            "enabled": config.enabled,
            "bypass_urgent": config.bypass_urgent,
            "updated_at": config.updated_at.isoformat(),
        },
        "currently_active": active,
        "held_count": held,
    }


@router.put("/quiet-hours")
async def update_quiet_hours(body: QuietHoursUpdateRequest, session: Session = Depends(get_session)) -> dict:
    if body.start_time is None and body.end_time is None and body.timezone is None and body.enabled is None and body.bypass_urgent is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")
    try:
        config = update_quiet_hours_config(session, start_time=body.start_time, end_time=body.end_time, tz=body.timezone, enabled=body.enabled, bypass_urgent=body.bypass_urgent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if config is None:
        raise HTTPException(status_code=404, detail="Quiet hours config not found")
    return {
        "status": "updated",
        "config": {
            "id": config.id,
            "start_time": config.start_time,
            "end_time": config.end_time,
            "timezone": config.timezone,
            "enabled": config.enabled,
            "bypass_urgent": config.bypass_urgent,
            "updated_at": config.updated_at.isoformat(),
        },
    }


@router.post("/digest")
async def trigger_digest() -> dict:
    try:
        sent = await generate_and_send_digest()
        return {"status": "sent" if sent else "empty", "message": "Digest sent successfully" if sent else "Nothing to include in digest"}
    except Exception as e:
        logger.error("Manual digest trigger failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Digest generation failed: {str(e)[:200]}")


@router.get("/digest/status")
async def digest_status() -> dict:
    settings = get_settings()
    return {
        "enabled": settings.digest_enabled,
        "hour": settings.digest_hour,
        "description": f"Daily digest fires at {settings.digest_hour}:00 local time",
    }


@router.get("/held")
async def list_held_notifications(session: Session = Depends(get_session)) -> dict:
    held_list = get_held_notifications(session)
    response_list = [
        {
            "id": h.id,
            "source_type": h.source_type,
            "external_id": h.external_id,
            "priority": h.priority,
            "title": h.title,
            "channel": h.channel,
            "notification_type": h.notification_type,
            "created_at": h.created_at.isoformat(),
        }
        for h in held_list
    ]
    return {"held": response_list, "count": len(response_list)}
