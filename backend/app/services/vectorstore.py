from __future__ import annotations

import logging
from typing import Any

import chromadb
import httpx

from app.config import get_settings
from app.services.http_client import get_ollama_client
from app.services.llm_rate_limiter import (
    estimate_tokens,
    check_rate_limit,
    check_budget,
    log_usage,
)

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None
COLLECTION_NAME = "source_items"


def init_vectorstore() -> chromadb.ClientAPI:
    global _client
    settings = get_settings()
    _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    _client.get_or_create_collection(
        name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )
    logger.info("ChromaDB initialized at %s", settings.chroma_persist_dir)
    return _client


def get_client() -> chromadb.ClientAPI:
    if _client is None:
        raise RuntimeError(
            "Vector store not initialized. Call init_vectorstore() first."
        )
    return _client


def get_collection() -> chromadb.Collection:
    client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if len(texts) == 0:
        return []
    settings = get_settings()
    input_tokens = sum(estimate_tokens(t) for t in texts)
    check_rate_limit()
    check_budget(input_tokens)
    try:
        http_client = get_ollama_client()
        response = await http_client.post(
            "/api/embed",
            json={"model": settings.ollama_embed_model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        log_usage("embedding", settings.ollama_embed_model, input_tokens, input_tokens)
        return data["embeddings"]
    except httpx.HTTPStatusError as e:
        logger.error("Ollama embed failed: %s", e)
        raise


async def add_documents(
    ids: list[str], texts: list[str], metadatas: list[dict[str, Any]]
) -> None:
    if len(texts) == 0:
        return
    embeddings = await embed_texts(texts)
    collection = get_collection()
    collection.upsert(
        ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
    )
    logger.info("Upserted %d documents into vector store", len(ids))


async def query(text: str, n_results: int = 5) -> dict[str, Any]:
    embeddings = await embed_texts([text])
    collection = get_collection()
    results = collection.query(
        query_embeddings=embeddings,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    return results


async def delete_documents(ids: list[str]) -> None:
    if len(ids) == 0:
        return
    collection = get_collection()
    collection.delete(ids=ids)
    logger.info("Deleted %d documents from vector store", len(ids))


def collection_count() -> int:
    collection = get_collection()
    return collection.count()
