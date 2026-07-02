"""Business rules for the agent work queue.

Wraps :mod:`repositories.queue_repo` with the v1-compatible field
translation (``project``/``agent`` external names ↔ ``project_id``/
``agent_id`` ORM names) and the priority/auto-routing rules ported from
v1 ``agent_queue.py`` + ``task_dispatch.TaskDispatcher.get_agent_for_task``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import QueueItem
from repositories import queue_repo
from schemas.queue import (
    QueueItemCreate,
    QueueItemRead,
    QueueItemUpdate,
    QueueOverview,
    QueueStats,
)

logger = logging.getLogger(__name__)

KANBAN_COLUMNS = ("urgent", "active", "review", "queued", "ideas")

# Default complexity → base priority bump. Higher priority sorts higher in
# the queued column (descending sort in ``list_items``).
COMPLEXITY_PRIORITY: dict[str, int] = {"quick": 5, "medium": 0, "deep": -5}
BUSINESS_ROUTING_TAGS = {"business", "company", "venture", "ventures"}
GROWTH_ROUTING_TAGS = {
    "bd",
    "email",
    "lead",
    "linkedin",
    "marketing",
    "outreach",
    "sales",
    "social",
}
DISPATCH_RELEVANT_FIELDS = {
    "agent_id",
    "complexity",
    "description",
    "doc_path",
    "priority",
    "project_id",
    "tags",
    "title",
}


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def to_read(item: QueueItem) -> QueueItemRead:
    """Map ORM ``QueueItem`` → v1-shaped :class:`QueueItemRead`."""
    return QueueItemRead(
        id=item.id,
        title=item.title,
        description=item.description or "",
        column=item.column,
        project=item.project_id,
        complexity=item.complexity,
        agent=item.agent_id,
        doc_path=item.doc_path,
        session_id=item.session_id,
        session_status=item.session_status,
        priority=item.priority,
        tags=list(item.tags or []),
        notes=item.notes or "",
        created_at=_iso(item.created_at),
        updated_at=_iso(item.updated_at),
        completed_at=_iso(item.completed_at),
    )


def _new_id() -> str:
    """v1-style queue id (``q_<timestamp>_<short-uuid>``)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"q_{stamp}_{uuid.uuid4().hex[:6]}"


def _normalize_changes(update: QueueItemUpdate) -> dict[str, Any]:
    """Translate v1 field names → ORM column names for ``update_item``."""
    raw = update.model_dump(exclude_unset=True)
    if "project" in raw:
        raw["project_id"] = raw.pop("project")
    if "agent" in raw:
        raw["agent_id"] = raw.pop("agent")
    return raw


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


async def overview(session: AsyncSession) -> QueueOverview:
    """Return the v1-shaped ``items + by_column + stats`` payload."""
    rows = [to_read(it) for it in await queue_repo.list_items(session)]

    by_column: dict[str, list[QueueItemRead]] = {c: [] for c in KANBAN_COLUMNS}
    for item in rows:
        by_column.setdefault(item.column, []).append(item)
    by_column["queued"].sort(key=lambda r: r.priority, reverse=True)

    running = sum(1 for r in rows if r.session_status == "running")
    stats = QueueStats(
        total=len(rows),
        urgent=len(by_column.get("urgent", [])),
        active=len(by_column.get("active", [])),
        review=len(by_column.get("review", [])),
        queued=len(by_column.get("queued", [])),
        ideas=len(by_column.get("ideas", [])),
        running_sessions=running,
    )
    return QueueOverview(items=rows, by_column=by_column, stats=stats)


async def get(session: AsyncSession, item_id: str) -> Optional[QueueItemRead]:
    """Fetch a single queue item by id (or ``None``)."""
    row = await queue_repo.get_item(session, item_id)
    return to_read(row) if row else None


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


async def create(session: AsyncSession, data: QueueItemCreate) -> QueueItemRead:
    """Create a queue item, auto-promoting priority for quick wins."""
    if data.project:
        await queue_repo.upsert_project_stub(session, data.project)
    base_priority = data.priority or 0
    bump = COMPLEXITY_PRIORITY.get(data.complexity or "medium", 0)
    row = await queue_repo.create_item(
        session,
        item_id=_new_id(),
        title=data.title,
        description=data.description or "",
        column=data.column or "queued",
        project=data.project,
        complexity=data.complexity or "medium",
        agent=data.agent,
        doc_path=data.doc_path,
        notes=data.notes or "",
        tags=data.tags,
        priority=base_priority + bump,
    )
    return to_read(row)


async def update(
    session: AsyncSession, item_id: str, data: QueueItemUpdate
) -> Optional[QueueItemRead]:
    """Patch a queue item; ``column='review'`` stamps ``completed_at``."""
    changes = _normalize_changes(data)
    if data.column in {"review", "done"}:
        changes.setdefault("completed_at", datetime.now(timezone.utc))
    if data.project and "project_id" in changes:
        await queue_repo.upsert_project_stub(session, changes["project_id"])
    existing = await queue_repo.get_item(session, item_id)
    if existing is None:
        return None
    if _should_mark_needs_update(existing, changes):
        changes["session_status"] = "needs_update"
    row = await queue_repo.update_item(session, item_id, changes)
    return to_read(row) if row else None


async def remove(session: AsyncSession, item_id: str) -> bool:
    """Delete a queue item; return ``False`` if missing."""
    return await queue_repo.delete_item(session, item_id)


def _should_mark_needs_update(item: QueueItem, changes: dict[str, Any]) -> bool:
    if item.column != "active":
        return False
    if changes.get("column") not in (None, "active"):
        return False
    if changes.get("session_status") is not None:
        return False
    return bool(DISPATCH_RELEVANT_FIELDS & changes.keys())


# ---------------------------------------------------------------------------
# Auto-routing
# ---------------------------------------------------------------------------


def suggest_agent_for_item(item: QueueItemRead) -> str:
    """Pick a sensible default agent based on tags + title keywords.

    Ported (and simplified) from v1
    ``task_dispatch.TaskDispatcher.get_agent_for_task``. Returns a known
    agent id from :data:`services.openclaw_client.AGENT_REGISTRY`. Defaults
    to ``jarvis`` if nothing matches.
    """
    tags = {t.lower() for t in item.tags}
    title = (item.title or "").lower()

    if {"research", "analysis"} & tags:
        return "aria"
    if {"finance", "budget"} & tags:
        return "peter"
    if {"medical", "health"} & tags:
        return "watson"
    if BUSINESS_ROUTING_TAGS & tags:
        if GROWTH_ROUTING_TAGS & tags or any(
            kw in title for kw in GROWTH_ROUTING_TAGS
        ):
            return "jc"
        return "willb"
    if {"bd", "sales", "marketing", "social", "linkedin"} & tags:
        return "jc"
    if {"startup", "product"} & tags:
        return "elon"
    return "jarvis"
