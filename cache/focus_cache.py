"""Ephemeral focus session state in Redis."""

import json
from datetime import datetime, timezone
from typing import Any, Optional

from cache.redis_client import get_redis

FOCUS_KEY = "mc:focus:session"
FOCUS_TTL_SECONDS = 7200
POMODORO_SECONDS = 25 * 60


async def get_session() -> Optional[dict[str, Any]]:
    """Load active focus session."""
    client = await get_redis()
    raw = await client.get(FOCUS_KEY)
    if not raw:
        return None
    return json.loads(raw)


async def save_session(session: dict[str, Any]) -> None:
    """Persist focus session with TTL."""
    client = await get_redis()
    await client.set(
        FOCUS_KEY,
        json.dumps(session),
        ex=FOCUS_TTL_SECONDS,
    )


async def clear_session() -> None:
    """End focus session."""
    client = await get_redis()
    await client.delete(FOCUS_KEY)


def elapsed_seconds(started_at: str) -> int:
    """Compute elapsed seconds from ISO started_at."""
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - started
    return int(delta.total_seconds())


async def enrich_status(session: dict[str, Any]) -> dict[str, Any]:
    """Add elapsed_seconds and optional remaining for pomodoro."""
    session = dict(session)
    elapsed = elapsed_seconds(session["started_at"])
    session["elapsed_seconds"] = elapsed
    if session.get("mode") == "pomodoro":
        remaining = session.get("remaining_seconds")
        if remaining is None:
            remaining = max(0, POMODORO_SECONDS - elapsed)
        session["remaining_seconds"] = remaining
    return session
