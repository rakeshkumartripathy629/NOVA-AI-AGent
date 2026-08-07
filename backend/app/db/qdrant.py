"""
Vector database client and collection management.

Backed by Qdrant by default; falls back to a Postgres-backed store
(JSONB vectors with Python cosine similarity) when Qdrant is unreachable.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings

logger = logging.getLogger(__name__)

_qdrant: Optional[AsyncQdrantClient] = None

DISTANCE = qmodels.Distance.COSINE

_PROBE_TTL_SECONDS = 60
_probe_result: Optional[bool] = None
_probe_time: float = 0.0

_PG_CHUNKS_TABLE = "nova_ai_vector_chunks"


def get_qdrant() -> AsyncQdrantClient:
    """Return the shared async Qdrant client."""
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=5,
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


# ----------------------------------------------------------------------
# Backend selection
# ----------------------------------------------------------------------
async def _qdrant_available() -> bool:
    """Probe Qdrant availability, caching the result briefly."""
    global _probe_result, _probe_time
    now = time.monotonic()
    if _probe_result is not None and (now - _probe_time) < _PROBE_TTL_SECONDS:
        return _probe_result
    try:
        client = get_qdrant()
        await asyncio.wait_for(client.get_collections(), timeout=3)
        _probe_result = True
        logger.debug("Qdrant reachable")
    except Exception as exc:  # noqa: BLE001
        _probe_result = False
        logger.warning("Qdrant unreachable, using Postgres vector store: %s", exc)
    _probe_time = now
    return _probe_result


async def _uses_postgres() -> bool:
    if not settings.QDRANT_AUTO_FALLBACK:
        return False
    return not await _qdrant_available()


# ----------------------------------------------------------------------
# Postgres fallback store
# ----------------------------------------------------------------------
async def _pg_ensure_table() -> None:
    """Create the vector chunk table if it does not exist."""
    from sqlalchemy import text

    from app.db.session import get_session_factory

    ddl = text(
        f"""
        CREATE TABLE IF NOT EXISTS {_PG_CHUNKS_TABLE} (
            collection TEXT NOT NULL,
            point_id   TEXT NOT NULL,
            vector     JSONB NOT NULL,
            payload    JSONB NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (collection, point_id)
        )
        """
    )
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(ddl)
        await session.commit()


async def _pg_upsert(collection: str, points: List[Dict[str, Any]]) -> None:
    from sqlalchemy import text

    from app.db.session import get_session_factory

    await _pg_ensure_table()
    stmt = text(
        f"""
        INSERT INTO {_PG_CHUNKS_TABLE} (collection, point_id, vector, payload)
        VALUES (:collection, :point_id, CAST(:vector AS JSONB), CAST(:payload AS JSONB))
        ON CONFLICT (collection, point_id)
        DO UPDATE SET vector = EXCLUDED.vector, payload = EXCLUDED.payload
        """
    )
    factory = get_session_factory()
    async with factory() as session:
        for point in points:
            await session.execute(
                stmt,
                {
                    "collection": collection,
                    "point_id": str(point["id"]),
                    "vector": json_dumps(point["vector"]),
                    "payload": json_dumps(point.get("payload", {})),
                },
            )
        await session.commit()


async def _pg_scroll_raw(collection: str) -> List[Dict[str, Any]]:
    """Return all rows for a collection as {id, vector, payload} dicts."""
    from sqlalchemy import text

    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                f"SELECT point_id, vector, payload FROM {_PG_CHUNKS_TABLE} WHERE collection = :collection"
            ),
            {"collection": collection},
        )
        rows = result.all()
    return [
        {"id": row[0], "vector": row[1], "payload": row[2]}
        for row in rows
    ]


async def _pg_delete_points(collection: str, point_ids: List[str]) -> None:
    from sqlalchemy import text

    from app.db.session import get_session_factory

    if not point_ids:
        return
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                f"DELETE FROM {_PG_CHUNKS_TABLE} WHERE collection = :collection AND point_id = ANY(:ids)"
            ),
            {"collection": collection, "ids": point_ids},
        )
        await session.commit()


async def _pg_delete_collection(collection: str) -> None:
    from sqlalchemy import text

    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(f"DELETE FROM {_PG_CHUNKS_TABLE} WHERE collection = :collection"),
            {"collection": collection},
        )
        await session.commit()


def _payload_matches(payload: Dict[str, Any], filter_payload: Optional[dict]) -> bool:
    """Evaluate a simple {key: value | [values]} filter against a payload dict."""
    if not filter_payload:
        return True
    for key, value in filter_payload.items():
        actual = payload.get(key)
        if isinstance(value, list):
            if not value or str(actual) not in {str(v) for v in value}:
                return False
        elif str(actual) != str(value):
            return False
    return True


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value)


# ----------------------------------------------------------------------
# Public vector-store API
# ----------------------------------------------------------------------
async def ensure_collection(
    name: str,
    dimension: int = settings.EMBEDDING_DIMENSION,
    distance: qmodels.Distance = DISTANCE,
) -> None:
    """Create a collection if it does not exist."""
    if await _uses_postgres():
        await _pg_ensure_table()
        return
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
    full = collection_name(name)
    if await _uses_postgres():
        await _pg_delete_collection(full)
        return
    client = get_qdrant()
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
    full = collection_name(collection)
    if await _uses_postgres():
        await _pg_upsert(full, points)
        return
    client = get_qdrant()
    await client.upsert(
        collection_name=full,
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
    if await _uses_postgres():
        full = collection_name(collection)
        rows = await _pg_scroll_raw(full)
        scored = []
        for row in rows:
            if not _payload_matches(row["payload"], payload_filter):
                continue
            score = _cosine(vector, row["vector"])
            if score_threshold is not None and score < score_threshold:
                continue
            scored.append({"id": row["id"], "score": score, "payload": row["payload"]})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

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
    if await _uses_postgres():
        full = collection_name(collection)
        rows = await _pg_scroll_raw(full)
        return [
            {"id": row["id"], "payload": row["payload"]}
            for row in rows
            if _payload_matches(row["payload"], filter_payload)
        ][:limit]

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
    if await _uses_postgres():
        await _pg_delete_points(collection_name(collection), [str(p) for p in point_ids])
        return
    client = get_qdrant()
    await client.delete(
        collection_name=collection_name(collection),
        points_selector=qmodels.PointIdsList(point_ids=[str(p) for p in point_ids]),
    )
