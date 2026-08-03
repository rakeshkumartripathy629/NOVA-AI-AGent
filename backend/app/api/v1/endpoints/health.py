"""
Service health endpoints.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.db.redis import redis_ping
from app.db.session import get_db
from app.db.session import check_db_connection

router = APIRouter()


@router.get("/live", summary="Liveness probe")
async def liveness() -> dict:
    """Returns 200 if the process is running."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.get("/ready", summary="Readiness probe")
async def readiness() -> dict:
    """Returns component status and a 503-flagged body if dependencies are down."""
    checks: dict = {}

    checks["database"] = "ok" if await check_db_connection() else "unavailable"
    checks["redis"] = "ok" if await redis_ping() else "unavailable"

    try:
        from app.db.qdrant import get_qdrant

        await get_qdrant().get_collections()
        checks["qdrant"] = "ok"
    except Exception:  # noqa: BLE001
        checks["qdrant"] = "unavailable"

    try:
        from app.core.storage import storage_service

        await storage_service.ensure_bucket()
        checks["storage"] = "ok"
    except Exception:  # noqa: BLE001
        checks["storage"] = "unavailable"

    return {
        "status": "ready" if all(v == "ok" for v in checks.values()) else "degraded",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }
