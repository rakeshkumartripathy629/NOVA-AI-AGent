"""
Vector store service for long-term memory.

Backed by the existing ``app.db.qdrant`` module (Qdrant with automatic
Postgres fallback). Configure the backend with ``MEMORY_VECTOR_STORE``:
  - ``auto``     -> Qdrant when reachable, otherwise Postgres JSONB vectors
  - ``qdrant``   -> force Qdrant
  - ``postgres`` -> force the Postgres fallback store

Memory points are namespaced by ``user_id`` in the payload so a query is always
scoped to the authenticated user. Failures are logged and swallowed so chat is
never blocked.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.db import qdrant

logger = get_logger("memory.vector_store")

MEMORY_COLLECTION = "memories"
SUMMARY_COLLECTION = "conversation_summaries"


def _collection(collection: str) -> str:
    return f"{settings.QDRANT_COLLECTION_PREFIX}_{collection}"


class VectorStoreService:
    """Small facade over the shared vector store for memory + summaries."""

    def __init__(self) -> None:
        self._mode = (settings.MEMORY_VECTOR_STORE or "auto").strip().lower()

    async def ensure_collection(self, name: str, dimension: int) -> None:
        """Create a collection if it does not exist (best effort)."""
        try:
            await qdrant.ensure_collection(name, dimension=dimension)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure vector collection %s: %s", name, exc)

    async def upsert(
        self,
        name: str,
        point_id: str,
        vector: List[float],
        payload: Dict[str, Any],
    ) -> None:
        """Upsert a single vector point (never raises)."""
        try:
            await qdrant.upsert_points(
                name,
                [{"id": point_id, "vector": vector, "payload": payload}],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector upsert failed (%s/%s): %s", name, point_id, exc)

    async def search(
        self,
        name: str,
        vector: List[float],
        user_id: UUID,
        top_k: int,
        threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search scoped to a single user. Returns [{id, score, payload}]."""
        try:
            return await qdrant.search_points(
                name,
                vector=vector,
                top_k=top_k,
                score_threshold=threshold,
                payload_filter={"user_id": str(user_id)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector search failed (%s): %s", name, exc)
            return []

    async def delete_user(self, name: str, user_id: UUID) -> None:
        """Delete all points belonging to a user (best effort)."""
        try:
            points = await qdrant.scroll_points(name, {"user_id": str(user_id)})
            if points:
                await qdrant.delete_points(name, [p["id"] for p in points])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector delete failed (%s): %s", name, exc)

    async def delete_point(self, name: str, point_id: str) -> None:
        try:
            await qdrant.delete_points(name, [point_id])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector delete failed (%s/%s): %s", name, point_id, exc)


vector_store = VectorStoreService()
