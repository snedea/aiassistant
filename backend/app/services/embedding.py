from __future__ import annotations

import json
import logging
from typing import Any

from sqlmodel import Session, select

from app.models.source_item import SourceItem
from app.services.vectorstore import add_documents, delete_documents, collection_count, get_collection, embed_texts

logger = logging.getLogger(__name__)


def _build_embed_text(source_type: str, title: str, content: str, raw_metadata: str) -> str:
    text = f"{title}\n\n{content}"
    try:
        meta = json.loads(raw_metadata)
    except json.JSONDecodeError:
        logger.warning("Failed to parse raw_metadata as JSON, skipping metadata enrichment")
        return text[:8000]

    if source_type == "calendar":
        location = meta.get("location")
        if location:
            text += f"\n\nLocation: {location}"
        dtstart = meta.get("dtstart")
        if dtstart:
            text += f"\nStart: {dtstart}"
        dtend = meta.get("dtend")
        if dtend:
            text += f"\nEnd: {dtend}"
        attendees = meta.get("attendees")
        if isinstance(attendees, list) and attendees:
            text += f"\nAttendees: {', '.join(attendees)}"
    elif source_type == "email":
        text += f"\n\nFrom: {meta.get('from', '')}"
        text += f"\nTo: {meta.get('to', '')}"
        text += f"\nDate: {meta.get('date', '')}"
    elif source_type == "notes":
        folder = meta.get("folder", "")
        if folder:
            text += f"\n\nFolder: {folder}"

    return text[:8000]


def _build_chroma_metadata(source_type: str, external_id: str, title: str, source_item_id: int) -> dict[str, str | int]:
    return {
        "source_type": source_type,
        "external_id": external_id,
        "title": title[:200],
        "source_item_id": source_item_id,
    }


def _chroma_id(source_type: str, external_id: str) -> str:
    return f"{source_type}:{external_id}"


async def embed_source_items(session: Session, source_type: str | None = None, item_ids: list[int] | None = None) -> int:
    stmt = select(SourceItem)
    if item_ids is not None and len(item_ids) > 0:
        stmt = stmt.where(SourceItem.id.in_(item_ids))
    elif source_type is not None:
        stmt = stmt.where(SourceItem.source_type == source_type)
    items = session.exec(stmt).all()

    if len(items) == 0:
        logger.info("No source items to embed")
        return 0

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for item in items:
        ids.append(_chroma_id(item.source_type, item.external_id))
        texts.append(_build_embed_text(item.source_type, item.title, item.content, item.raw_metadata))
        metadatas.append(_build_chroma_metadata(item.source_type, item.external_id, item.title, item.id))

    for i in range(0, len(ids), 50):
        await add_documents(ids[i:i + 50], texts[i:i + 50], metadatas[i:i + 50])

    logger.info("Embedded %d source items (source_type=%s)", len(ids), source_type)
    return len(ids)


async def semantic_search(query_text: str, source_type: str | None = None, n_results: int = 10) -> list[dict[str, Any]]:
    embeddings = await embed_texts([query_text])
    collection = get_collection()

    query_kwargs: dict[str, Any] = {
        "query_embeddings": embeddings,
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if source_type is not None:
        query_kwargs["where"] = {"source_type": source_type}

    results = collection.query(**query_kwargs)

    if not results["ids"][0]:
        return []

    response: list[dict[str, Any]] = []
    for i in range(len(results["ids"][0])):
        response.append({
            "id": results["ids"][0][i],
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
            "score": 1.0 - results["distances"][0][i],
        })
    return response
