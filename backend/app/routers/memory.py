from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth import require_auth
from app.database import get_session
from app.services.memory import get_facts, deactivate_fact

router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_facts(category: str | None = None, session: Session = Depends(get_session)) -> dict:
    facts = get_facts(session, category=category, active_only=True)
    response_list = [
        {
            "id": fact.id,
            "category": fact.category,
            "subject": fact.subject,
            "content": fact.content,
            "source_type": fact.source_type,
            "source_ref": fact.source_ref,
            "confidence": fact.confidence,
            "created_at": fact.created_at.isoformat(),
            "updated_at": fact.updated_at.isoformat(),
        }
        for fact in facts
    ]
    return {"facts": response_list}


@router.delete("/{fact_id}")
async def delete_fact(fact_id: int, session: Session = Depends(get_session)) -> dict:
    result = deactivate_fact(session, fact_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "deactivated", "fact_id": fact_id}
