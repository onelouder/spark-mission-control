"""Kanban task business logic."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.kanban import Task
from repositories import task_repo
from schemas.task import QuickTask, TaskRead, TaskReorder, TaskUpdate

logger = logging.getLogger(__name__)


def get_energy_for_task(title: str) -> str:
    """Assign energy level based on task title keywords."""
    title_lower = title.lower()
    urgent_words = (
        "urgent", "critical", "deadline", "important",
        "complex", "meeting", "decision",
    )
    simple_words = ("update", "check", "review", "organize", "file", "simple")
    if any(word in title_lower for word in urgent_words):
        return "high_burn"
    if any(word in title_lower for word in simple_words):
        return "brain_dead"
    return "low_stakes"


def task_to_read(task: Task) -> TaskRead:
    """Map ORM task to API DTO (v1 field names)."""
    return TaskRead(
        id=str(task.id),
        title=task.title,
        description=task.description or "",
        column=task.column_id,
        position=task.position,
        energy=task.energy,
        source_type=task.source_type,
        source_id=task.source_id,
        source_url=task.source_url,
        category=task.category,
        notes=task.notes,
        stuck_since=_iso(task.stuck_since),
        snoozed_until=_iso(task.snoozed_until),
        show_in_briefing=task.show_in_briefing,
        project_id=str(task.project_id) if task.project_id else None,
        context_id=task.context_id,
        flow_state=task.flow_state,
        blocked_reason=task.blocked_reason,
        created_at=_iso(task.created_at) or "",
        updated_at=_iso(task.updated_at) or "",
    )


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


async def list_all(session: AsyncSession) -> list[TaskRead]:
    """List tasks with stuck_since defaults."""
    rows = await task_repo.list_tasks(session)
    out: list[TaskRead] = []
    for task in rows:
        if task.stuck_since is None:
            task.stuck_since = task.updated_at
        out.append(task_to_read(task))
    return out


async def create(session: AsyncSession, data: QuickTask) -> TaskRead:
    """Create task at top of column."""
    column = data.column if data.column else "unsorted"
    energy = get_energy_for_task(data.title)
    task = await task_repo.create_task(
        session,
        title=data.title,
        column_id=column,
        energy=energy,
    )
    return task_to_read(task)


async def update(
    session: AsyncSession,
    task_id: str,
    data: TaskUpdate,
) -> Optional[TaskRead]:
    """Update task fields."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        return None

    task = await task_repo.get_task(session, uid)
    if task is None:
        return None

    now = datetime.now(timezone.utc)
    old_column = task.column_id

    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if data.energy is not None:
        task.energy = data.energy
    if data.notes is not None:
        task.notes = data.notes

    if data.column is not None and data.column != old_column:
        task.column_id = data.column
        task.stuck_since = now
        task.position = 0
        await session.execute(
            sql_update(Task)
            .where(Task.column_id == data.column, Task.id != uid)
            .values(position=Task.position + 1)
        )

    if data.position is not None:
        task.position = data.position

    task.updated_at = now
    await session.flush()
    return task_to_read(task)


async def reorder(
    session: AsyncSession,
    data: TaskReorder,
) -> Optional[dict[str, Any]]:
    """Reorder task within or across columns."""
    try:
        uid = uuid.UUID(data.task_id)
    except ValueError:
        return None

    task = await task_repo.get_task(session, uid)
    if task is None:
        return None

    old_column = task.column_id
    new_column = data.column
    new_position = data.position
    now = datetime.now(timezone.utc)

    stmt = select(Task).where(
        Task.column_id == new_column,
        Task.id != uid,
    )
    result = await session.execute(stmt)
    column_tasks = sorted(result.scalars().all(), key=lambda t: t.position)
    column_tasks.insert(new_position, task)

    for index, row in enumerate(column_tasks):
        row.position = index

    if old_column != new_column:
        task.column_id = new_column
        task.stuck_since = now

    task.position = new_position
    task.updated_at = now
    await session.flush()
    return {"success": True, "task": task_to_read(task).model_dump()}


async def remove(session: AsyncSession, task_id: str) -> bool:
    """Delete a task."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        return False
    return await task_repo.delete_task(session, uid)


async def to_kanban(session: AsyncSession, task_id: str) -> bool:
    """Move task to unsorted and hide from briefing."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        return False
    task = await task_repo.get_task(session, uid)
    if task is None:
        return False
    task.column_id = "unsorted"
    task.show_in_briefing = False
    task.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return True


async def snooze(
    session: AsyncSession,
    task_id: str,
    hours: float = 1.0,
) -> Optional[str]:
    """Snooze task; return wake_at ISO string."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        return None
    task = await task_repo.get_task(session, uid)
    if task is None:
        return None
    wake_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    task.snoozed_until = wake_at
    task.show_in_briefing = False
    await session.flush()
    return wake_at.isoformat()


async def clear_column(session: AsyncSession, column: str) -> int:
    """Delete all tasks in a column."""
    return await task_repo.delete_tasks_in_column(session, column)
