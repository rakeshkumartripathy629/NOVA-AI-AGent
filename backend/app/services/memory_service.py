"""
Memory service — public orchestrator for the long-term memory feature.

Wires together extraction, embedding, vector storage and retrieval, and exposes
the management operations used by the API. Every operation is scoped to the
authenticated ``user_id``. Failures are contained so chat never breaks.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.memory import MemoryCategory, MemoryItem
from app.services import conversation_summary as summary_service
from app.services.conversation_search import search_user_conversations
from app.services.embedding import embedding_service
from app.services.memory_context import build_memory_context
from app.services.memory_extractor import extract_memories as _extract_persist
from app.services.memory_retriever import retrieve_memories
from app.services.vector_store import MEMORY_COLLECTION, vector_store

logger = get_logger("memory.service")

_EXTRACTION_TASKS: set = set()


def memory_enabled(user) -> bool:
    """Global flag + per-user preference check."""
    if not settings.MEMORY_ENABLED:
        return False
    prefs = getattr(user, "preferences", None) or {}
    return prefs.get("memory_enabled", True) is not False


async def recall_memories(
    user_id: UUID,
    query: str,
    limit: Optional[int] = None,
) -> List[MemoryItem]:
    """Return the user's most relevant memories (semantic + ranking)."""
    try:
        return await retrieve_memories(user_id, query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory recall failed: %s", exc)
        return []


async def recall_context(user_id: UUID, query: str) -> str:
    """Build the 'Remembered context' block: memories + relevant summaries."""
    try:
        memories = await retrieve_memories(user_id, query)
        summaries = await summary_service.relevant_summaries(user_id, query)
        return build_memory_context(memories, summaries)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory context build failed: %s", exc)
        return ""


async def extract_and_store(
    user_id: UUID,
    organization_id: Optional[UUID],
    conversation_id: Optional[UUID],
    user_content: str,
    assistant_content: str,
) -> List[MemoryItem]:
    """Background extraction + dedup/merge + embedding + vector indexing."""
    try:
        return await _extract_persist(
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            user_content=user_content,
            assistant_content=assistant_content,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory extraction failed: %s", exc)
        return []


def schedule_extraction(
    user_id: UUID,
    organization_id: Optional[UUID],
    conversation_id: Optional[UUID],
    user_content: str,
    assistant_content: str,
) -> None:
    """Fire-and-forget extraction + summarization, never blocking the reply."""
    task = asyncio.create_task(
        extract_and_store(
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            user_content=user_content,
            assistant_content=assistant_content,
        )
    )
    _EXTRACTION_TASKS.add(task)
    task.add_done_callback(_EXTRACTION_TASKS.discard)
    summary_service.schedule_summary(conversation_id, user_id)


# --------------------------------------------------------------------------
# Management helpers (used by the /memory API)
# --------------------------------------------------------------------------
async def list_memories(
    db: AsyncSession,
    user_id: UUID,
    search: Optional[str] = None,
    category: Optional[MemoryCategory] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    query = select(MemoryItem).where(
        MemoryItem.user_id == user_id,
        MemoryItem.is_deleted.is_(False),
        MemoryItem.superseded_by_id.is_(None),
    )
    if search:
        query = query.where(MemoryItem.content.ilike(f"%{search.strip()}%"))
    if category:
        query = query.where(MemoryItem.category == category)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(MemoryItem.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())
    return {
        "items": items,
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


async def get_memory(db: AsyncSession, user_id: UUID, memory_id: UUID) -> Optional[MemoryItem]:
    result = await db.execute(
        select(MemoryItem).where(
            MemoryItem.id == memory_id,
            MemoryItem.user_id == user_id,
            MemoryItem.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def create_memory(
    db: AsyncSession,
    user_id: UUID,
    organization_id: Optional[UUID],
    content: str,
    category: MemoryCategory,
) -> MemoryItem:
    """Persist a manually added memory and index its embedding."""
    item = MemoryItem(
        user_id=user_id,
        organization_id=organization_id,
        content=content.strip(),
        category=category,
        confidence=1.0,
        metadata_={"auto": False},
    )
    db.add(item)
    await db.flush()
    try:
        [vec] = await embedding_service.embed([item.content])
        item.embedding = vec
        await vector_store.ensure_collection(MEMORY_COLLECTION, embedding_service.dimension())
        await vector_store.upsert(
            MEMORY_COLLECTION,
            str(item.id),
            vec,
            {
                "user_id": str(user_id),
                "memory_id": str(item.id),
                "content": item.content,
                "category": item.category.value,
                "importance": item.importance,
                "confidence": item.confidence,
                "created_at": item.created_at.isoformat() if item.created_at else "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Manual memory embedding failed: %s", exc)
    await db.commit()
    await db.refresh(item)
    return item


async def update_memory(
    db: AsyncSession,
    user_id: UUID,
    memory_id: UUID,
    updates: Dict[str, Any],
) -> Optional[MemoryItem]:
    item = await get_memory(db, user_id, memory_id)
    if not item:
        return None
    for field, value in updates.items():
        if value is not None:
            setattr(item, field, value)
    if "content" in updates or "category" in updates:
        try:
            [vec] = await embedding_service.embed([item.content])
            item.embedding = vec
            await vector_store.upsert(
                MEMORY_COLLECTION,
                str(item.id),
                vec,
                {
                    "user_id": str(user_id),
                    "memory_id": str(item.id),
                    "content": item.content,
                    "category": item.category.value,
                    "importance": item.importance,
                    "confidence": item.confidence,
                    "created_at": item.created_at.isoformat() if item.created_at else "",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory re-embedding failed: %s", exc)
    await db.commit()
    await db.refresh(item)
    return item


async def delete_memory(db: AsyncSession, user_id: UUID, memory_id: UUID) -> bool:
    item = await get_memory(db, user_id, memory_id)
    if not item:
        return False
    item.is_deleted = True
    item.deleted_at = datetime.utcnow()
    await db.commit()
    await vector_store.delete_point(MEMORY_COLLECTION, str(memory_id))
    return True


async def clear_memories(db: AsyncSession, user_id: UUID) -> int:
    """Soft-delete all of the user's memories and their vectors."""
    result = await db.execute(
        select(MemoryItem).where(
            MemoryItem.user_id == user_id,
            MemoryItem.is_deleted.is_(False),
        )
    )
    items = list(result.scalars().all())
    for item in items:
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
    await db.commit()
    await vector_store.delete_user(MEMORY_COLLECTION, user_id)
    return len(items)


async def search_memories(
    db: AsyncSession,
    user_id: UUID,
    query: str,
    limit: int = 20,
) -> List[MemoryItem]:
    """Semantic search over the user's memories (used by POST /memory/search)."""
    from app.services.memory_retriever import similarity_for

    items = await list_memories(db, user_id, page_size=200)
    scored = []
    for item in items["items"]:
        sim = similarity_for(item, query)
        if sim > 0.1:
            scored.append((item, sim))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [item for item, _score in scored[:limit]]
