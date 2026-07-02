"""Async Redis connection pool."""

from typing import Optional

import redis.asyncio as redis

from config import get_settings

_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Return shared Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping_redis() -> bool:
    """Health check."""
    try:
        client = await get_redis()
        return await client.ping()
    except Exception:
        return False
