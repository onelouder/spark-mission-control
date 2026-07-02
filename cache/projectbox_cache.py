"""Short-TTL Redis cache for the Project-Box task list.

Project-Box rebuilds its task list from disk on every ``GET /api/tasks``,
which is cheap (~hundreds of small files) but still a few ms per call.
Cache the full list under ``mc:projectbox:list`` with a 30-second TTL so
the briefing assembly + read-heavy UI calls don't re-walk the vault.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from cache.redis_client import get_redis
from config import get_settings

logger = logging.getLogger(__name__)

LIST_KEY = "mc:projectbox:list"


def _ttl() -> int:
    return int(get_settings().projectbox_cache_ttl_seconds or 30)


async def load_list() -> Optional[list[dict[str, Any]]]:
    """Return the cached task list, or ``None`` on miss / decode failure."""
    try:
        redis = await get_redis()
        raw = await redis.get(LIST_KEY)
    except Exception:  # pragma: no cover — Redis outage shouldn't kill us
        logger.exception("projectbox_cache: load failed")
        return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("projectbox_cache: dropping malformed payload")
        return None
    return data if isinstance(data, list) else None


async def store_list(payload: list[dict[str, Any]]) -> None:
    """Cache the task list for :data:`_ttl` seconds."""
    try:
        redis = await get_redis()
        await redis.set(LIST_KEY, json.dumps(payload, default=str), ex=_ttl())
    except Exception:  # pragma: no cover
        logger.exception("projectbox_cache: store failed")


async def invalidate() -> int:
    """Drop the cached list (called after any mutation)."""
    try:
        redis = await get_redis()
        return int(await redis.delete(LIST_KEY))
    except Exception:  # pragma: no cover
        logger.exception("projectbox_cache: invalidate failed")
        return 0
