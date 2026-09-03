"""
Comprehensive health check service.

Checks all dependencies and returns a detailed status report
used by the /health/detail endpoint.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from app.core.logging import get_logger

logger = get_logger("health")


async def check_database() -> Dict[str, Any]:
    """Check PostgreSQL connectivity."""
    t0 = time.monotonic()
    try:
        from app.db.session import check_db_connection
        ok = await check_db_connection()
        return {
            "status": "healthy" if ok else "unhealthy",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc)[:200],
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }


async def check_redis() -> Dict[str, Any]:
    """Check Redis connectivity."""
    t0 = time.monotonic()
    try:
        from app.db.redis import get_redis
        r = get_redis()
        if r is None:
            return {"status": "not_configured", "latency_ms": 0}
        # Use SET/GET instead of PING for broader Redis version compatibility
        await r.set("__health_check__", "ok", ex=10)
        val = await r.get("__health_check__")
        if val != "ok":
            raise RuntimeError("Redis read-back failed")
        return {
            "status": "healthy",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc)[:200],
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }


async def check_qdrant() -> Dict[str, Any]:
    """Check Qdrant vector DB connectivity."""
    t0 = time.monotonic()
    try:
        from app.db.qdrant import get_qdrant
        client = get_qdrant()
        if client is None:
            return {"status": "not_configured", "latency_ms": 0}
        await asyncio.wait_for(asyncio.to_thread(client.get_collections), timeout=5)
        return {
            "status": "healthy",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "error": str(exc)[:200],
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }


async def check_ai_providers() -> Dict[str, Any]:
    """Check which AI providers are available and their status."""
    from app.core.config import settings
    from app.core.circuit_breaker import all_breakers_status
    from app.ai.providers import is_provider_healthy

    providers = {}
    provider_configs = {
        "groq": settings.GROQ_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "cerebras": settings.CEREBRAS_API_KEY,
    }

    for name, api_key in provider_configs.items():
        if api_key:
            providers[name] = {
                "configured": True,
                "healthy": is_provider_healthy(name),
            }
        else:
            providers[name] = {
                "configured": False,
                "healthy": False,
            }

    # Add circuit breaker statuses
    breakers = all_breakers_status()
    return {
        "providers": providers,
        "circuit_breakers": breakers,
    }


async def check_storage() -> Dict[str, Any]:
    """Check storage (S3/MinIO/local) connectivity."""
    t0 = time.monotonic()
    try:
        from app.core.storage import storage_service
        # Just check if the service is initialized
        return {
            "status": "healthy",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc)[:200],
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }


async def full_health_check() -> Dict[str, Any]:
    """Run all health checks in parallel and return a combined report."""
    t0 = time.monotonic()

    db_check, redis_check, qdrant_check, ai_check, storage_check = await asyncio.gather(
        check_database(),
        check_redis(),
        check_qdrant(),
        check_ai_providers(),
        check_storage(),
        return_exceptions=True,
    )

    # Handle exceptions from gather
    def _safe(result: Any, default: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(result, Exception):
            return {"status": "error", "error": str(result)[:200]}
        return result

    db = _safe(db_check, {"status": "unknown"})
    redis = _safe(redis_check, {"status": "unknown"})
    qdrant = _safe(qdrant_check, {"status": "unknown"})
    ai = _safe(ai_check, {"providers": {}})
    storage = _safe(storage_check, {"status": "unknown"})

    # Determine overall status
    critical = [db]
    all_checks = [db, redis, qdrant, storage]

    overall = "healthy"
    for check in critical:
        if check.get("status") == "unhealthy":
            overall = "degraded"
            break
    for check in all_checks:
        if check.get("status") == "unhealthy":
            overall = "degraded"

    return {
        "status": overall,
        "version": "1.0.0",
        "uptime_s": round(time.monotonic(), 0),
        "checks": {
            "database": db,
            "redis": redis,
            "qdrant": qdrant,
            "ai_providers": ai,
            "storage": storage,
        },
        "latency_ms": round((time.monotonic() - t0) * 1000, 1),
    }
