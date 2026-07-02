"""Redis-backed cache for the daily briefing payload.

Stored under ``mc:briefing:{YYYY-MM-DD}`` with a 5-minute TTL. The
briefing service writes a JSON-encoded :class:`schemas.briefing.Briefing`
and reads it back as a plain dict for the API layer.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from cache.redis_client import get_redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "mc:briefing"
DEFAULT_TTL_SECONDS = 300


def _key(for_date: date) -> str:
    return f"{KEY_PREFIX}:{for_date.isoformat()}"


async def load(for_date: date) -> Optional[dict[str, Any]]:
    """Return the cached briefing for ``for_date`` or ``None``."""
    try:
        redis = await get_redis()
        raw = await redis.get(_key(for_date))
    except Exception:  # pragma: no cover — defensive
        logger.exception("briefing_cache: load failed for %s", for_date)
        return None
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("briefing_cache: invalid JSON for %s; ignoring", for_date)
        return None
    return payload


async def store(
    for_date: date, payload: dict[str, Any], *, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    """Persist ``payload`` under the date key with ``ttl_seconds`` TTL."""
    try:
        redis = await get_redis()
        await redis.set(
            _key(for_date),
            json.dumps(payload, default=_json_default),
            ex=ttl_seconds,
        )
    except Exception:  # pragma: no cover
        logger.exception("briefing_cache: store failed for %s", for_date)


async def invalidate(for_date: Optional[date] = None) -> int:
    """Drop the cache for ``for_date`` (default: every cached day).

    Returns the number of keys evicted.
    """
    redis = await get_redis()
    if for_date is not None:
        return int(await redis.delete(_key(for_date)))
    # Scan + delete; SCAN keeps the loop responsive for large keyspaces.
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=f"{KEY_PREFIX}:*")
        if keys:
            deleted += int(await redis.delete(*keys))
        if cursor == 0:
            break
    return deleted


def _json_default(value: Any) -> Any:
    """Serializer for ``datetime``/``date`` that returns ISO-8601 strings."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
