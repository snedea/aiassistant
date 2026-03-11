from __future__ import annotations
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app


def test_chat_creates_conversation() -> None:
    with TestClient(app) as client:
        with patch("app.services.chat_pipeline.chat_completion", new_callable=AsyncMock, return_value="Hello! How can I help?"):
            response = client.post("/chat", json={"message": "Hi there"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["conversation_id"], str)
        assert len(data["conversation_id"]) > 0
        assert data["reply"] == "Hello! How can I help?"


def test_chat_continues_conversation() -> None:
    with TestClient(app) as client:
        with patch("app.services.chat_pipeline.chat_completion", new_callable=AsyncMock, return_value="First reply") as mock_llm:
            response = client.post("/chat", json={"message": "Hello"})
            conversation_id = response.json()["conversation_id"]

            mock_llm.return_value = "Second reply"
            response = client.post("/chat", json={"message": "Follow up", "conversation_id": conversation_id})

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == conversation_id
        assert data["reply"] == "Second reply"
        call_args = mock_llm.call_args[0][0]
        assert len(call_args) >= 4


def test_chat_history_endpoint() -> None:
    with TestClient(app) as client:
        with patch("app.services.chat_pipeline.chat_completion", new_callable=AsyncMock, return_value="Test reply"):
            response = client.post("/chat", json={"message": "Test message"})
            conversation_id = response.json()["conversation_id"]

        response = client.get(f"/chat/history/{conversation_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Test message"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "Test reply"


def test_chat_llm_unavailable() -> None:
    with TestClient(app) as client:
        with patch("app.services.chat_pipeline.chat_completion", new_callable=AsyncMock, side_effect=Exception("Connection refused")):
            response = client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 502
        assert "LLM service unavailable" in response.json()["detail"]
