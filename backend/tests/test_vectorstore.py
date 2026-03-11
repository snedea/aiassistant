from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vectorstore import (
    init_vectorstore,
    get_client,
    embed_texts,
    add_documents,
    collection_count,
)
import app.services.vectorstore as vs_module


def test_init_vectorstore_creates_client(tmp_path):
    mock_settings = MagicMock(
        chroma_persist_dir=str(tmp_path / "chroma"),
        ollama_embed_model="nomic-embed-text",
        ollama_base_url="http://localhost:11434",
    )
    with patch("app.services.vectorstore.get_settings", return_value=mock_settings):
        vs_module._client = None
        init_vectorstore()
        assert vs_module._client is not None
        assert collection_count() == 0
        vs_module._client = None


def test_get_client_raises_if_not_initialized():
    vs_module._client = None
    with pytest.raises(RuntimeError, match="not initialized"):
        get_client()


@pytest.mark.asyncio
async def test_embed_texts_calls_ollama():
    mock_response = MagicMock()
    mock_response.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    mock_response.raise_for_status = MagicMock()

    mock_settings = MagicMock(
        ollama_base_url="http://localhost:11434",
        ollama_embed_model="nomic-embed-text",
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.vectorstore.get_settings", return_value=mock_settings), \
         patch("app.services.vectorstore.get_ollama_client", return_value=mock_client):
        result = await embed_texts(["hello"])
        assert result == [[0.1, 0.2, 0.3]]
        mock_client.post.assert_called_once_with(
            "/api/embed",
            json={"model": "nomic-embed-text", "input": ["hello"]},
        )


@pytest.mark.asyncio
async def test_add_documents_upserts(tmp_path):
    mock_settings = MagicMock(
        chroma_persist_dir=str(tmp_path / "chroma"),
        ollama_embed_model="nomic-embed-text",
        ollama_base_url="http://localhost:11434",
    )
    with patch("app.services.vectorstore.get_settings", return_value=mock_settings):
        vs_module._client = None
        init_vectorstore()
        with patch("app.services.vectorstore.embed_texts", new_callable=AsyncMock, return_value=[[0.1, 0.2, 0.3]]):
            await add_documents(
                ids=["doc1"],
                texts=["test content"],
                metadatas=[{"source": "test"}],
            )
        assert collection_count() == 1
        vs_module._client = None


@pytest.mark.asyncio
async def test_add_documents_empty_is_noop():
    with patch("app.services.vectorstore.embed_texts", new_callable=AsyncMock) as mock_embed:
        await add_documents(ids=[], texts=[], metadatas=[])
        mock_embed.assert_not_called()


def test_health_vectorstore_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    mock_settings = MagicMock(
        chroma_persist_dir=str(tmp_path / "chroma"),
        ollama_embed_model="nomic-embed-text",
        ollama_base_url="http://localhost:11434",
        database_url=f"sqlite:///{tmp_path}/test.db",
        host="0.0.0.0",
        port=8000,
    )
    with patch("app.services.vectorstore.get_settings", return_value=mock_settings):
        vs_module._client = None
        init_vectorstore()
        client = TestClient(app)
        response = client.get("/health/vectorstore")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["document_count"] == 0
        vs_module._client = None
