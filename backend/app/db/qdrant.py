"""
Qdrant vector database client and collection management.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings

logger = logging.getLogger(__name__)

_qdrant: Optional[AsyncQdrantClient] = None

DISTANCE = qmodels.Distance.COSINE


def get_qdrant() -> AsyncQdrantClient:
    """Return the shared async Qdrant client."""
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=30,
        )
    return _qdrant


async def close_qdrant() -> None:
    global _qdrant
    if _qdrant is not None:
        await _qdrant.close()
        _qdrant = None


def collection_name(name: str) -> str:
    """Namespaced collection name."""
    return f"{settings.QDRANT_COLLECTION_PREFIX}_{name}"


async def ensure_collection(
    name: str,
    dimension: int = settings.EMBEDDING_DIMENSION,
    distance: qmodels.Distance = DISTANCE,
) -> None:
    """Create a collection if it does not exist."""
    client = get_qdrant()
    full = collection_name(name)
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if full not in names:
        await client.create_collection(
            collection_name=full,
            vectors_config=qmodels.VectorParams(size=dimension, distance=distance),
        )
        logger.info("Created Qdrant collection %s", full)


async def delete_collection(name: str) -> None:
    """Delete a collection."""
    client = get_qdrant()
    full = collection_name(name)
    try:
        await client.delete_collection(collection_name=full)
    except Exception:
        logger.warning("Failed to delete collection %s", full, exc_info=True)


async def upsert_points(
    collection: str,
    points: List[Dict[str, Any]],
) -> None:
    """Upsert points into a collection.

    Each point dict: {id, vector, payload}
    """
    client = get_qdrant()
    await client.upsert(
        collection_name=collection_name(collection),
        points=[
            qmodels.PointStruct(
                id=point["id"],
                vector=point["vector"],
                payload=point.get("payload", {}),
            )
            for point in points
        ],
    )


def _to_filter(payload_filter: Optional[dict]) -> Optional[qmodels.Filter]:
    """Build a Qdrant filter from a simple {key: value} dict or match-any dict.

    Supports:
      {"field": value}                         -> match value
      {"field": ["a", "b"]}                    -> match any of the values
    """
    if not payload_filter:
        return None
    must = []
    for key, value in payload_filter.items():
        if isinstance(value, list) and value:
            must.append(
                qmodels.FieldCondition(
                    key=key,
                    match=qmodels.MatchAny(any=[str(v) for v in value]),
                )
            )
        else:
            must.append(
                qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=str(value)))
            )
    return qmodels.Filter(must=must)


async def search_points(
    collection: str,
    vector: List[float],
    top_k: int = settings.RAG_TOP_K,
    score_threshold: Optional[float] = None,
    payload_filter: Optional[dict] = None,
) -> List[dict]:
    """Semantic search over a collection."""
    client = get_qdrant()
    results = await client.query_points(
        collection_name=collection_name(collection),
        query=vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=_to_filter(payload_filter),
        with_payload=True,
    )
    return [
        {
            "id": hit.id,
            "score": hit.score,
            "payload": hit.payload,
        }
        for hit in results.points
    ]


async def scroll_points(
    collection: str,
    filter_payload: Optional[dict] = None,
    limit: int = 1000,
) -> List[dict]:
    """Retrieve all points in a collection (optionally filtered)."""
    client = get_qdrant()
    results, _ = await client.scroll(
        collection_name=collection_name(collection),
        limit=limit,
        with_payload=True,
        with_vectors=False,
        scroll_filter=_to_filter(filter_payload),
    )
    return [{"id": p.id, "payload": p.payload} for p in results]


async def delete_points(
    collection: str,
    point_ids: List[str],
) -> None:
    """Delete points by id."""
    client = get_qdrant()
    await client.delete(
        collection_name=collection_name(collection),
        points_selector=qmodels.PointIdsList(point_ids=point_ids),
    )
