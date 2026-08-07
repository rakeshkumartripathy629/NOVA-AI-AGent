"""
RAG pipeline: text chunking, embeddings and Qdrant retrieval.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.ai.providers import embedding_provider
from app.core.config import settings
from app.core.logging import get_logger
from app.db.qdrant import delete_points, ensure_collection, scroll_points, search_points, upsert_points

logger = get_logger("ai.rag")

CHUNKS_COLLECTION = "chunks"


def chunk_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """Split text into overlapping chunks on paragraph/sentence boundaries."""
    size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.RAG_CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= size:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # Prefer breaking at a sentence/paragraph boundary near the end
        if end < len(text):
            boundary = max(
                text.rfind("\n\n", start, end),
                text.rfind(". ", start, end),
                text.rfind(".\n", start, end),
                text.rfind("! ", start, end),
                text.rfind("? ", start, end),
            )
            if boundary > start + size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


async def _ensure_chunks_collection(dimension: int = settings.EMBEDDING_DIMENSION) -> None:
    await ensure_collection(CHUNKS_COLLECTION, dimension=dimension)


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed texts in batches using a provider that supports embeddings."""
    if not texts:
        return []
    provider = embedding_provider()
    vectors: List[List[float]] = []
    for i in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + settings.EMBEDDING_BATCH_SIZE]
        vectors.extend(await provider.embed(batch))
    return vectors


async def index_document(
    *,
    knowledge_base_id: UUID,
    document_id: UUID,
    title: str,
    content: str,
    source_type: str = "text",
    organization_id: Optional[UUID] = None,
) -> int:
    """Chunk, embed and upsert a document into the vector store."""
    chunks = chunk_text(content)
    if not chunks:
        logger.info("Document %s has no indexable content", document_id)
        return 0

    await _ensure_chunks_collection()
    vectors = await embed_texts(chunks)

    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        point_id = hashlib.md5(f"{document_id}:{i}".encode()).hexdigest()
        points.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "knowledge_base_id": str(knowledge_base_id),
                    "document_id": str(document_id),
                    "organization_id": str(organization_id) if organization_id else None,
                    "title": title,
                    "content": chunk,
                    "source_type": source_type,
                    "chunk_index": i,
                },
            }
        )

    await upsert_points(CHUNKS_COLLECTION, points)
    logger.info("Indexed %d chunks for document %s", len(points), document_id)
    await recompute_kb_index(knowledge_base_id)
    return len(points)


async def delete_document_chunks(document_id: UUID) -> None:
    """Remove all chunks belonging to a document."""
    points = await scroll_points(
        CHUNKS_COLLECTION,
        filter_payload={"document_id": str(document_id)},
    )
    if points:
        await delete_points(CHUNKS_COLLECTION, [str(p["id"]) for p in points])
        knowledge_base_id = points[0]["payload"].get("knowledge_base_id")
        if knowledge_base_id:
            await recompute_kb_index(knowledge_base_id)


async def recompute_kb_index(knowledge_base_id: UUID) -> None:
    """Refresh a knowledge base's index metadata from the vector store."""
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.knowledge_base import KnowledgeBase

    try:
        await _ensure_chunks_collection()
        points = await scroll_points(
            CHUNKS_COLLECTION,
            filter_payload={"knowledge_base_id": str(knowledge_base_id)},
            limit=100000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to recompute KB index %s: %s", knowledge_base_id, exc)
        return

    chunk_count = len(points)
    document_count = len(
        {p["payload"].get("document_id") for p in points if p["payload"].get("document_id")}
    )

    factory = get_session_factory()
    async with factory() as db:
        kb = await db.get(KnowledgeBase, knowledge_base_id)
        if kb:
            kb.is_indexed = chunk_count > 0
            kb.total_chunks = chunk_count
            kb.document_count = document_count
            await db.commit()
            logger.info(
                "KB %s index refreshed: %d chunks, %d documents",
                knowledge_base_id,
                chunk_count,
                document_count,
            )


async def retrieve(
    query: str,
    knowledge_base_ids: List[UUID],
    top_k: int = settings.RAG_TOP_K,
    score_threshold: Optional[float] = None,
    organization_id: Optional[UUID] = None,
) -> List[Dict[str, Any]]:
    """Search chunks across the given knowledge bases."""
    if not knowledge_base_ids:
        return []

    await _ensure_chunks_collection()
    vectors = await embed_texts([query])
    if not vectors:
        return []

    must = {"knowledge_base_id": [str(kb) for kb in knowledge_base_ids]}
    if organization_id:
        must["organization_id"] = str(organization_id)

    results = await search_points(
        CHUNKS_COLLECTION,
        vectors[0],
        top_k=top_k,
        score_threshold=score_threshold or settings.RAG_SIMILARITY_THRESHOLD,
        payload_filter=must,
    )

    return [
        {
            "chunk_id": r["id"],
            "document_id": r["payload"].get("document_id"),
            "knowledge_base_id": r["payload"].get("knowledge_base_id"),
            "title": r["payload"].get("title", ""),
            "content": r["payload"].get("content", ""),
            "score": r["score"],
            "source_type": r["payload"].get("source_type", "text"),
        }
        for r in results
    ]
