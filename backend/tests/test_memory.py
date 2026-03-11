from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.database import get_engine
from app.main import app
from app.models.fact import Fact
from app.services.memory import _clean_extracted_facts


def test_clean_extracted_facts_valid_json() -> None:
    raw = '[{"category": "preference", "subject": "Coffee", "content": "User prefers black coffee"}]'
    result = _clean_extracted_facts(raw)
    assert len(result) == 1
    assert result[0]["category"] == "preference"
    assert result[0]["subject"] == "Coffee"
    assert result[0]["content"] == "User prefers black coffee"


def test_clean_extracted_facts_empty_array() -> None:
    result = _clean_extracted_facts("[]")
    assert result == []


def test_clean_extracted_facts_invalid_json() -> None:
    result = _clean_extracted_facts("not json at all")
    assert result == []


def test_clean_extracted_facts_code_fence() -> None:
    raw = '```json\n[{"category": "personal", "subject": "Name", "content": "User name is John"}]\n```'
    result = _clean_extracted_facts(raw)
    assert len(result) == 1
    assert result[0]["subject"] == "Name"


def test_clean_extracted_facts_invalid_category() -> None:
    raw = '[{"category": "invalid_cat", "subject": "Test", "content": "Test fact"}]'
    result = _clean_extracted_facts(raw)
    assert result == []


def test_clean_extracted_facts_missing_keys() -> None:
    raw = '[{"category": "preference", "subject": "Coffee"}]'
    result = _clean_extracted_facts(raw)
    assert result == []


def test_memory_list_endpoint() -> None:
    with TestClient(app) as client:
        engine = get_engine()
        with Session(engine) as session:
            fact = Fact(
                category="preference",
                subject="Test",
                content="Test fact",
                source_type="conversation",
                source_ref="test-conv-id",
            )
            session.add(fact)
            session.commit()
            session.refresh(fact)
            fact_id = fact.id

        response = client.get("/memory")
        assert response.status_code == 200
        data = response.json()
        assert "facts" in data
        assert len(data["facts"]) >= 1
        found = [f for f in data["facts"] if f["subject"] == "Test"]
        assert len(found) >= 1
        assert found[0]["category"] == "preference"

        # Cleanup
        with Session(engine) as session:
            f = session.get(Fact, fact_id)
            if f:
                session.delete(f)
                session.commit()


def test_memory_delete_endpoint() -> None:
    with TestClient(app) as client:
        engine = get_engine()
        with Session(engine) as session:
            fact = Fact(
                category="personal",
                subject="Delete me",
                content="To be deleted",
                source_type="conversation",
                source_ref="test",
            )
            session.add(fact)
            session.commit()
            session.refresh(fact)
            fact_id = fact.id

        response = client.delete(f"/memory/{fact_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deactivated"

        response = client.get("/memory")
        facts = response.json()["facts"]
        found = [f for f in facts if f["id"] == fact_id]
        assert len(found) == 0

        # Cleanup
        with Session(engine) as session:
            f = session.get(Fact, fact_id)
            if f:
                session.delete(f)
                session.commit()


def test_memory_delete_not_found() -> None:
    with TestClient(app) as client:
        response = client.delete("/memory/99999")
        assert response.status_code == 404


def test_memory_filter_by_category() -> None:
    with TestClient(app) as client:
        engine = get_engine()
        with Session(engine) as session:
            f1 = Fact(
                category="preference",
                subject="Filter pref",
                content="A preference fact",
                source_type="conversation",
                source_ref="test",
            )
            f2 = Fact(
                category="personal",
                subject="Filter personal",
                content="A personal fact",
                source_type="conversation",
                source_ref="test",
            )
            session.add(f1)
            session.add(f2)
            session.commit()
            session.refresh(f1)
            session.refresh(f2)
            f1_id = f1.id
            f2_id = f2.id

        response = client.get("/memory?category=preference")
        assert response.status_code == 200
        facts = response.json()["facts"]
        for f in facts:
            assert f["category"] == "preference"

        # Cleanup
        with Session(engine) as session:
            for fid in (f1_id, f2_id):
                f = session.get(Fact, fid)
                if f:
                    session.delete(f)
                    session.commit()
