from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.main import create_app
from app.database import get_session
import app.models  # noqa: F401


@pytest.fixture
def test_app():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    with patch("app.database.init_db"), \
         patch("app.database.get_engine", return_value=engine), \
         patch("app.services.llm_rate_limiter.get_engine", return_value=engine), \
         patch("app.services.vectorstore.init_vectorstore"), \
         patch("app.services.rules_engine.ensure_default_rules"), \
         patch("app.services.quiet_hours.ensure_quiet_hours_config"), \
         patch("app.services.scanner.start_scanner", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.scanner.stop_scanner", new_callable=AsyncMock), \
         patch("app.services.slack_bot.start_slack_bot", new_callable=AsyncMock, return_value=None), \
         patch("app.services.slack_bot.stop_slack_bot", new_callable=AsyncMock):
        app = create_app()
        app.dependency_overrides[get_session] = override_session
        client = TestClient(app)
        yield client, engine


def test_admin_stats(test_app: tuple) -> None:
    client, engine = test_app
    with patch("app.routers.admin.collection_count", return_value=0):
        response = client.get("/admin/stats")
    assert response.status_code == 200
    data = response.json()
    assert "facts" in data
    assert "conversations" in data
    assert "source_items" in data
    assert "source_items_total" in data
    assert "vector_documents" in data


def test_admin_clear_memory_invalid_scope(test_app: tuple) -> None:
    client, engine = test_app
    response = client.post("/admin/memory/clear", json={"scope": "invalid"})
    assert response.status_code == 400


def test_admin_clear_facts_empty(test_app: tuple) -> None:
    client, engine = test_app
    response = client.post("/admin/memory/clear", json={"scope": "facts"})
    assert response.status_code == 200
    assert response.json()["facts_cleared"] == 0


def test_admin_clear_conversations_empty(test_app: tuple) -> None:
    client, engine = test_app
    response = client.post("/admin/memory/clear", json={"scope": "conversations"})
    assert response.status_code == 200
    assert response.json()["conversations_cleared"] == 0


def test_admin_clear_all_empty(test_app: tuple) -> None:
    client, engine = test_app
    with patch("app.services.admin.get_collection", return_value=MagicMock()):
        response = client.post("/admin/memory/clear", json={"scope": "all"})
    assert response.status_code == 200
    assert response.json()["facts_cleared"] == 0
    assert response.json()["conversations_cleared"] == 0
    assert response.json()["source_items_cleared"] == 0


def test_admin_connections(test_app: tuple) -> None:
    client, engine = test_app
    with patch(
        "app.routers.admin.test_all_connections",
        new_callable=AsyncMock,
        return_value=[{"name": "ollama", "configured": False, "reachable": False, "error": "not set"}],
    ):
        response = client.get("/admin/connections")
    assert response.status_code == 200
    data = response.json()
    assert "connections" in data
    assert data["count"] == 1


def test_admin_test_connection_invalid(test_app: tuple) -> None:
    client, engine = test_app
    response = client.post("/admin/connections/bogus/test")
    assert response.status_code == 400


def test_admin_sync_invalid_source(test_app: tuple) -> None:
    client, engine = test_app
    response = client.post("/admin/sync/bogus")
    assert response.status_code == 400


def test_admin_scanner_status(test_app: tuple) -> None:
    client, engine = test_app
    response = client.get("/admin/scanner/status")
    assert response.status_code == 200
    data = response.json()
    assert "scanners" in data
    assert isinstance(data["count"], int)
