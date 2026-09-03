"""
Memory retriever.

Implements the retrieval flow used before every LLM call:

  query -> embed -> semantic search (scoped to user) -> rank by
  similarity + importance + recency + confidence -> deduplicate -> relevance
  threshold -> token limit.

When the vector search fails (embedding provider down, store unavailable) it
falls back to keyword scoring so chat keeps working. Never raises.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.memory import MemoryItem
from app.services.embedding import embedding_service, hash_embed
from app.services.vector_store import MEMORY_COLLECTION, vector_store

logger = get_logger("memory.retriever")


def _recency_score(item: MemoryItem) -> float:
    """1.0 for fresh memories, decaying to ~0 over 30 days."""
    created = item.created_at
    if not created:
        return 0.5
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = max(0.0, (now - created).days)
    return max(0.0, 1.0 - days / 30.0)


def rank_scores(
    similarity: float,
    importance: int,
    recency: float,
    confidence: float,
) -> float:
    """Weighted combination used for final ranking."""
    return (
        settings.MEMORY_WEIGHT_SIMILARITY * similarity
        + settings.MEMORY_WEIGHT_IMPORTANCE * (min(importance, 5) / 5.0)
        + settings.MEMORY_WEIGHT_RECENCY * recency
        + settings.MEMORY_WEIGHT_CONFIDENCE * confidence
    )


def _dedupe(items: List[Tuple[MemoryItem, float]]) -> List[Tuple[MemoryItem, float]]:
    """Drop near-duplicate memories, keeping the highest-scoring one."""
    result: List[Tuple[MemoryItem, float]] = []
    seen_norms: set = set()
    for item, score in sorted(items, key=lambda pair: pair[1], reverse=True):
        norm = " ".join(
            w for w in (item.content or "").lower().split() if len(w) >= 3
        )
        if norm and norm in seen_norms:
            continue
        if norm:
            seen_norms.add(norm)
        result.append((item, score))
    return result


async def retrieve_memories(
    user_id: UUID,
    query: str,
    limit: Optional[int] = None,
) -> List[MemoryItem]:
    """Return the user's most relevant memories for ``query``.

    Filters by the authenticated user, applies relevance threshold, token limit
    and deduplication. Best-effort; returns [] on any failure.
    """
    if not settings.MEMORY_ENABLED:
        return []
    limit = limit or settings.MEMORY_RECALL_LIMIT
    query = (query or "").strip()
    if not query:
        return []

    # Fast path: if user has no memories, skip embedding entirely
    _no_mem_cache_key = f"nova:mem:count:{user_id}"
    try:
        from app.core.config import settings as _s
        async with get_db_context() as db:
            cnt_result = await db.execute(
                select(MemoryItem.id).where(
                    MemoryItem.user_id == user_id,
                    MemoryItem.is_deleted.is_(False),
                    MemoryItem.superseded_by_id.is_(None),
                ).limit(1)
            )
            has_any = cnt_result.scalar_one_or_none() is not None
        if not has_any:
            return []
    except Exception:
        pass  # continue anyway

    try:
        [qvec] = await embedding_service.embed([query])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query embedding failed: %s", exc)
        return []

    # 1) Semantic search over this user's memories (vector store).
    hits = await vector_store.search(
        MEMORY_COLLECTION,
        qvec,
        user_id=user_id,
        top_k=max(limit * 4, 20),
        threshold=None,
    )

    async with get_db_context() as db:
        result = await db.execute(
            select(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.is_deleted.is_(False),
                MemoryItem.superseded_by_id.is_(None),
            )
        )
        all_items = list(result.scalars().all())

    if not all_items:
        return []

    by_id = {item.id: item for item in all_items}
    similarity = {item.id: 0.0 for item in all_items}

    # 2) If the vector store returned nothing (unavailable/empty), fall back to
    #    keyword similarity using the same embedder so it stays consistent.
    if hits:
        for hit in hits:
            mid = hit["payload"].get("memory_id")
            if not mid:
                continue
            try:
                sim_id = UUID(str(mid))
            except ValueError:
                continue
            if sim_id in similarity:
                similarity[sim_id] = float(hit.get("score", 0.0))
    else:
        qvec_norm = hash_embed(query)
        keyword_hits = {}
        for item in all_items:
            try:
                sim = _cosine(item.embedding or hash_embed(item.content), qvec_norm)
            except Exception:  # noqa: BLE001
                sim = 0.0
            if sim > 0.0:
                keyword_hits[item.id] = sim
        if not keyword_hits and not similarity:
            # Vector store down AND nothing stored: keyword token-overlap scoring.
            qw = {w for w in query.lower().split() if len(w) >= 3}
            for item in all_items:
                words = {w for w in item.content.lower().split() if len(w) >= 3}
                overlap = len(qw & words)
                if overlap:
                    keyword_hits[item.id] = overlap / max(len(qw), 1)
        similarity.update(keyword_hits)

    # 3) Rank: similarity + importance + recency + confidence.
    ranked: List[Tuple[MemoryItem, float]] = []
    for item in all_items:
        sim = similarity.get(item.id, 0.0)
        score = rank_scores(sim, item.importance, _recency_score(item), item.confidence)
        ranked.append((item, score))

    # 4) Relevance threshold (only strongly relevant memories are injected).
    ranked = [(item, s) for item, s in ranked if s >= settings.MEMORY_RELEVANCE_THRESHOLD]

    # 5) Deduplicate near-identical memories.
    ranked = _dedupe(ranked)
    ranked.sort(key=lambda pair: pair[1], reverse=True)

    # 6) Token limit on the selected memories.
    selected = _apply_token_limit(ranked, settings.MEMORY_TOKEN_LIMIT)
    selected = selected[:limit]

    # Track usage (best effort, never blocks).
    if selected:
        try:
            async with get_db_context() as db:
                for item in selected:
                    item.use_count = item.use_count + 1
                    item.last_used_at = func.now()
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Memory usage tracking failed: %s", exc)

    return selected


def _apply_token_limit(
    ranked: List[Tuple[MemoryItem, float]], token_limit: int
) -> List[MemoryItem]:
    """Keep the highest-ranked memories while staying under the token budget."""
    from app.services.embedding import count_tokens

    selected: List[MemoryItem] = []
    used = 0
    for item, _score in ranked:
        tokens = count_tokens(item.content)
        if used + tokens > token_limit and selected:
            break
        used += tokens
        selected.append(item)
    return selected


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def similarity_for(item: MemoryItem, query: str) -> float:
    """Expose a raw similarity estimate (used by the search endpoint)."""
    qvec = hash_embed(query)
    try:
        return _cosine(item.embedding or hash_embed(item.content), qvec)
    except Exception:  # noqa: BLE001
        return 0.0
