from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_no_auth_required(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret-key-123")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    assert response.status_code == 200


def test_protected_401_without_token(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret-key-123")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/memory")
    assert response.status_code == 401


def test_protected_401_wrong_token(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret-key-123")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/memory", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401


def test_protected_200_correct_token(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret-key-123")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/memory", headers={"Authorization": "Bearer test-secret-key-123"})
    assert response.status_code == 200


def test_no_auth_when_key_empty(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/memory")
    assert response.status_code == 200
