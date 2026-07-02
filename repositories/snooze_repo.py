"""Persistence for ``core.snooze_items``.

Snooze items hide briefing entries until ``wake_at`` passes. The
:mod:`services.snooze_service` wake-sweep loop deletes entries past their
``wake_at`` and (for kanban-task snoozes) re-sets ``show_in_briefing`` on
the referenced :class:`db.orm.kanban.Task`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import SnoozeItem


async def list_snoozed(
    session: AsyncSession, *, only_awake: bool = False
) -> Sequence[SnoozeItem]:
    """Return all snooze rows; pass ``only_awake=True`` for sweep candidates."""
    stmt = select(SnoozeItem).order_by(SnoozeItem.wake_at)
    if only_awake:
        stmt = stmt.where(SnoozeItem.wake_at <= datetime.now(timezone.utc))
    result = await session.execute(stmt)
    return result.scalars().all()


async def snoozed_source_ids(
    session: AsyncSession, *, item_type: str
) -> set[str]:
    """Return source IDs currently hidden by snoozes of ``item_type``."""
    now = datetime.now(timezone.utc)
    rows = await list_snoozed(session)
    return {
        row.source_id
        for row in rows
        if row.item_type == item_type and row.wake_at > now
    }


async def upsert(
    session: AsyncSession,
    *,
    item_type: str,
    source_id: str,
    wake_at: datetime,
    title: Optional[str] = None,
    context: Optional[str] = None,
    original_block: Optional[str] = None,
) -> SnoozeItem:
    """Create or update the snooze row keyed by (item_type, source_id)."""
    stmt = select(SnoozeItem).where(
        SnoozeItem.item_type == item_type, SnoozeItem.source_id == source_id
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.wake_at = wake_at
        if title is not None:
            existing.title = title
        if context is not None:
            existing.context = context
        if original_block is not None:
            existing.original_block = original_block
        await session.flush()
        return existing
    row = SnoozeItem(
        id=uuid.uuid4(),
        item_type=item_type,
        source_id=source_id,
        title=title,
        context=context,
        original_block=original_block,
        wake_at=wake_at,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def remove(session: AsyncSession, snooze_id: str) -> bool:
    """Delete a snooze by primary key; ``False`` if missing."""
    row = await session.get(SnoozeItem, uuid.UUID(snooze_id))
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def remove_expired(
    session: AsyncSession, *, now: Optional[datetime] = None
) -> Sequence[SnoozeItem]:
    """Delete snooze rows whose ``wake_at`` is in the past; return what we removed."""
    cutoff = now or datetime.now(timezone.utc)
    stmt = select(SnoozeItem).where(SnoozeItem.wake_at <= cutoff)
    expired = list((await session.execute(stmt)).scalars().all())
    if expired:
        await session.execute(
            delete(SnoozeItem).where(
                SnoozeItem.id.in_([row.id for row in expired])
            )
        )
        await session.flush()
    return expired
