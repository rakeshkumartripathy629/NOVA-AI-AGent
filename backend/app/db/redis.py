"""
Redis clients: connection pool, cache helpers and rate-limit / lock helpers.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """Return the shared async Redis client, creating it on first use."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        )
    return _redis


async def close_redis() -> None:
    """Close the shared Redis client."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


class Cache:
    """Thin JSON cache helper on top of Redis."""

    prefix = settings.CACHE_PREFIX

    @staticmethod
    def _key(key: str) -> str:
        return f"{Cache.prefix}{key}"

    @staticmethod
    async def get(key: str) -> Optional[Any]:
        client = get_redis()
        try:
            raw = await client.get(Cache._key(key))
            return json.loads(raw) if raw else None
        except Exception:
            logger.warning("Cache read failed for %s", key, exc_info=True)
            return None

    @staticmethod
    async def set(key: str, value: Any, ttl: Optional[int] = None) -> None:
        client = get_redis()
        try:
            await client.set(
                Cache._key(key),
                json.dumps(value),
                ex=ttl or settings.CACHE_TTL,
            )
        except Exception:
            logger.warning("Cache write failed for %s", key, exc_info=True)

    @staticmethod
    async def delete(key: str) -> None:
        client = get_redis()
        try:
            await client.delete(Cache._key(key))
        except Exception:
            logger.warning("Cache delete failed for %s", key, exc_info=True)

    @staticmethod
    async def delete_pattern(pattern: str) -> None:
        client = get_redis()
        try:
            async for key in client.scan_iter(match=Cache._key(pattern)):
                await client.delete(key)
        except Exception:
            logger.warning("Cache pattern delete failed for %s", pattern, exc_info=True)


async def acquire_lock(name: str, timeout: int = 30, blocking: bool = True) -> bool:
    """Acquire a Redis-based distributed lock (best effort, non-atomic fallback)."""
    client = get_redis()
    try:
        return bool(
            await client.set(
                Cache._key(f"lock:{name}"),
                "1",
                ex=timeout,
                nx=True,
            )
        )
    except Exception:
        logger.warning("Lock acquisition failed for %s", name, exc_info=True)
        return not blocking


async def release_lock(name: str) -> None:
    """Release a Redis-based distributed lock."""
    client = get_redis()
    try:
        await client.delete(Cache._key(f"lock:{name}"))
    except Exception:
        logger.warning("Lock release failed for %s", name, exc_info=True)


async def redis_ping() -> bool:
    """Return True if Redis is reachable."""
    try:
        await get_redis().ping()
        return True
    except Exception:
        return False
