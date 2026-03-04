"""
Shared Redis connection pool for the entire application.

All modules that need Redis (rate limiter, LLM cache, analytics cache,
anomaly deduplication) import get_redis() from here instead of creating
their own pools. This means ONE pool of TCP connections to Redis regardless
of how many features use it, rather than N pools (one per feature).

Usage:
    from app.core.redis import get_redis

    r = get_redis()
    await r.set("key", "value", ex=300)
    value = await r.get("key")

Lifecycle:
    - Pool is created lazily on first call to get_redis().
    - close_redis() is called once in main.py lifespan shutdown.
    - Never call close_redis() from feature code — only from lifespan.
"""
import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """
    Return the application-wide shared Redis client.

    Creates the connection pool on first call (lazy init). Subsequent calls
    return the same instance. Thread-safe within asyncio's single-threaded
    event loop.
    """
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,          # shared pool — sized for all features
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        logger.info("Shared Redis connection pool created")
    return _pool


async def close_redis() -> None:
    """
    Close the shared Redis connection pool on application shutdown.

    Called once from main.py lifespan. After this, get_redis() will
    create a new pool if called again (safe for test teardown).
    """
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Shared Redis connection pool closed")
