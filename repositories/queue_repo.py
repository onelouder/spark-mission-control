"""Persistence for the agents queue (``agents.queue_items`` + ``agents.agent_projects``).

Mirrors the access patterns used by v1's ``agent_queue.py`` (CRUD by id,
list-all, move-to-column) but executes against PostgreSQL via SQLAlchemy
async.

All functions take an :class:`AsyncSession` so the calling service can
control commit boundaries (the FastAPI dependency ``get_session`` commits
on success and rolls back on exception).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import AgentProject, QueueItem


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# AgentProject
# ---------------------------------------------------------------------------


async def list_projects(session: AsyncSession) -> Sequence[AgentProject]:
    """Return every ``AgentProject`` ordered by name."""
    result = await session.execute(select(AgentProject).order_by(AgentProject.name))
    return result.scalars().all()


async def get_project(
    session: AsyncSession, project_id: str
) -> Optional[AgentProject]:
    """Fetch a single project by primary key."""
    return await session.get(AgentProject, project_id)


async def upsert_project_stub(
    session: AsyncSession,
    project_id: str,
    *,
    name: Optional[str] = None,
) -> AgentProject:
    """Insert a minimal project row if missing; return existing otherwise.

    Mirrors v1 ``migrate_queue`` behavior: orphan queue items referencing
    a non-existent project create a stub so the FK can land.
    """
    existing = await session.get(AgentProject, project_id)
    if existing is not None:
        return existing
    now = _utc_now()
    project = AgentProject(
        id=project_id,
        name=name or project_id,
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    await session.flush()
    return project


# ---------------------------------------------------------------------------
# QueueItem
# ---------------------------------------------------------------------------


async def list_items(session: AsyncSession) -> Sequence[QueueItem]:
    """Return every queue item ordered by ``column`` then descending priority.

    The descending priority sort keeps the highest-priority backlog at the
    top of each Kanban column, matching v1 behavior.
    """
    result = await session.execute(
        select(QueueItem).order_by(
            QueueItem.column.asc(),
            QueueItem.priority.desc(),
            QueueItem.created_at.asc(),
        )
    )
    return result.scalars().all()


async def get_item(session: AsyncSession, item_id: str) -> Optional[QueueItem]:
    """Fetch a single queue item by primary key."""
    return await session.get(QueueItem, item_id)


async def create_item(
    session: AsyncSession,
    *,
    item_id: str,
    title: str,
    description: str = "",
    column: str = "queued",
    project: Optional[str] = None,
    complexity: str = "medium",
    agent: Optional[str] = None,
    doc_path: Optional[str] = None,
    notes: str = "",
    tags: Optional[list[str]] = None,
    priority: int = 0,
) -> QueueItem:
    """Persist a new queue item."""
    now = _utc_now()
    item = QueueItem(
        id=item_id,
        title=title,
        description=description,
        column=column,
        project_id=project,
        complexity=complexity,
        agent_id=agent,
        doc_path=doc_path,
        notes=notes,
        tags=list(tags or []),
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    await session.flush()
    return item


async def update_item(
    session: AsyncSession,
    item_id: str,
    changes: dict[str, object],
) -> Optional[QueueItem]:
    """Apply a partial update to a queue item.

    ``changes`` is a flat dict produced by
    ``QueueItemUpdate.model_dump(exclude_unset=True)`` — the service layer
    is responsible for translating v1 field names (``project`` / ``agent``)
    into ORM fields (``project_id`` / ``agent_id``).

    Returns the updated row, or ``None`` if the id does not exist.
    """
    item = await session.get(QueueItem, item_id)
    if item is None:
        return None
    for key, value in changes.items():
        if hasattr(item, key):
            setattr(item, key, value)
    item.updated_at = _utc_now()
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item_id: str) -> bool:
    """Delete a queue item; return ``False`` if missing."""
    item = await session.get(QueueItem, item_id)
    if item is None:
        return False
    await session.delete(item)
    await session.flush()
    return True


async def list_by_session_status(
    session: AsyncSession, status: str
) -> Sequence[QueueItem]:
    """Return queue items currently in a given dispatch ``session_status``."""
    result = await session.execute(
        select(QueueItem).where(QueueItem.session_status == status)
    )
    return result.scalars().all()
