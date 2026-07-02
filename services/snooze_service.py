"""Snooze management + background wake-sweep loop.

Two responsibilities:

1. **API helpers** — create/list/delete :class:`SnoozeItem` rows, expose
   them via :mod:`api.routers.briefing`.
2. **Wake sweep** — a single asyncio task that runs every
   :data:`SWEEP_INTERVAL_SECONDS` and removes expired snoozes. Legacy
   kanban task rows also get their ``show_in_briefing`` flag restored.

The sweep guards against multi-worker double-fire by acquiring a Redis
lock (``mc2:snooze-sweep``) with a TTL of the sweep interval. If the
lock can't be acquired the loop just naps until the next tick.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from cache import briefing_cache
from cache.redis_client import get_redis
from db.orm.core import SnoozeItem
from db.orm.kanban import Task
from db.session import get_session_factory
from repositories import snooze_repo

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 60.0
LOCK_KEY = "mc2:snooze-sweep"


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


async def create_snooze(
    session: AsyncSession,
    *,
    item_type: str,
    source_id: str,
    wake_at: datetime,
    title: Optional[str] = None,
    context: Optional[str] = None,
    original_block: Optional[str] = None,
) -> SnoozeItem:
    """Create or update a snooze row.

    Legacy kanban task rows also get ``show_in_briefing=False``. Project-Box
    task snoozes are handled by source-id filtering in briefing/runway.
    """
    row = await snooze_repo.upsert(
        session,
        item_type=item_type,
        source_id=source_id,
        wake_at=wake_at,
        title=title,
        context=context,
        original_block=original_block,
    )
    if item_type == "task":
        await _set_task_briefing_visibility(session, source_id, visible=False)
    await briefing_cache.invalidate()
    return row


async def list_snoozes(session: AsyncSession) -> Sequence[SnoozeItem]:
    """List all snooze rows ordered by wake time."""
    return await snooze_repo.list_snoozed(session)


async def remove_snooze(session: AsyncSession, snooze_id: str) -> bool:
    """Delete a snooze row by id; ``False`` if missing."""
    deleted = await snooze_repo.remove(session, snooze_id)
    if deleted:
        await briefing_cache.invalidate()
    return deleted


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


async def sweep_once(session: AsyncSession) -> int:
    """Process expired snoozes in a single transactional pass.

    Returns the number of snoozes woken (i.e. removed).
    """
    expired = await snooze_repo.remove_expired(session)
    if not expired:
        return 0
    for row in expired:
        if row.item_type == "task":
            await _set_task_briefing_visibility(session, row.source_id, visible=True)
    await briefing_cache.invalidate()
    logger.info(
        "snooze_service: swept %d expired snooze item(s)", len(expired)
    )
    return len(expired)


async def _set_task_briefing_visibility(
    session: AsyncSession, task_id: str, *, visible: bool
) -> None:
    """Flip ``show_in_briefing`` on a kanban task when the snooze targets one."""
    try:
        uid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        return
    task = await session.get(Task, uid)
    if task is None:
        return
    task.show_in_briefing = visible
    if visible:
        task.snoozed_until = None
        task.updated_at = datetime.now(timezone.utc)
    await session.flush()


# ---------------------------------------------------------------------------
# Lifespan task
# ---------------------------------------------------------------------------


async def _try_acquire_lock(ttl_seconds: float) -> bool:
    """Acquire ``LOCK_KEY`` for ``ttl_seconds``; return ``False`` if taken."""
    try:
        redis = await get_redis()
        return bool(
            await redis.set(LOCK_KEY, "1", ex=int(ttl_seconds), nx=True)
        )
    except Exception:  # pragma: no cover — Redis outage shouldn't kill the loop
        logger.exception("snooze_service: lock acquire failed")
        return True  # fail-open so the sweep still runs single-worker


async def run_sweep_loop() -> None:
    """Background loop intended for the FastAPI lifespan."""
    factory = get_session_factory()
    logger.info("snooze_service: sweep loop starting (interval %.0fs)", SWEEP_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            if not await _try_acquire_lock(SWEEP_INTERVAL_SECONDS):
                logger.debug("snooze_service: another worker holds the sweep lock")
                continue
            async with factory() as session:
                try:
                    woken = await sweep_once(session)
                    if woken:
                        await session.commit()
                    else:
                        await session.rollback()
                except Exception:
                    logger.exception("snooze_service: sweep iteration failed")
                    await session.rollback()
        except asyncio.CancelledError:
            logger.info("snooze_service: sweep loop cancelled")
            raise
        except Exception:  # pragma: no cover
            logger.exception("snooze_service: unexpected loop error; continuing")


def start_in_lifespan() -> asyncio.Task:
    """Spawn the sweep task. Cancel from the lifespan teardown."""
    return asyncio.create_task(run_sweep_loop(), name="mc2-snooze-sweep")


async def stop_in_lifespan(task: Optional[asyncio.Task]) -> None:
    """Cancel ``task`` and await its exit; tolerant of ``None``."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("snooze_service: sweep task crashed during shutdown")
