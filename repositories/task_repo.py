"""Kanban task persistence."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.kanban import Task


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def list_tasks(session: AsyncSession) -> Sequence[Task]:
    """Return all tasks ordered by column and position."""
    stmt = (
        select(Task)
        .order_by(Task.column_id, Task.position, Task.updated_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Optional[Task]:
    """Fetch a single task by id."""
    return await session.get(Task, task_id)


async def create_task(
    session: AsyncSession,
    *,
    title: str,
    column_id: str,
    energy: str,
) -> Task:
    """Insert a new task at the top of a column.

    Bumps existing positions in a single bulk UPDATE so creates are O(1)
    network round-trips regardless of column size.
    """
    await session.execute(
        update(Task)
        .where(Task.column_id == column_id)
        .values(position=Task.position + 1)
    )

    now = _utc_now()
    task = Task(
        id=uuid.uuid4(),
        title=title,
        description="",
        column_id=column_id,
        position=0,
        energy=energy,
        source_type="manual",
        stuck_since=now,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    await session.flush()
    return task


async def delete_task(session: AsyncSession, task_id: uuid.UUID) -> bool:
    """Delete task; return False if missing."""
    task = await session.get(Task, task_id)
    if task is None:
        return False
    await session.delete(task)
    await session.flush()
    return True


async def delete_tasks_in_column(session: AsyncSession, column_id: str) -> int:
    """Delete all tasks in a column; return count deleted."""
    result = await session.execute(
        delete(Task)
        .where(Task.column_id == column_id)
        .returning(Task.id)
    )
    return len(result.all())
