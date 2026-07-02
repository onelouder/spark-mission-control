"""Pydantic DTOs for the agent queue + dispatch surface.

Mirrors the v1 ``agent_queue.QueueItem`` shape (string ids like
``q_20260501_001``, list-of-tags, ``project`` field) so existing UIs and
``parity_diff.py`` payloads continue to match.

Fields land in three layers:

- :class:`QueueItemRead` — full row as returned by ``GET /api/queue``.
- :class:`QueueItemCreate` / :class:`QueueItemUpdate` — request bodies.
- :class:`DispatchRequest` / :class:`DispatchStatus` — dispatch surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AgentProjectRead(BaseModel):
    """Agent project (container for queue items)."""

    id: str
    name: str
    description: Optional[str] = None
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentProjectCreate(BaseModel):
    """Create a new agent project."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str
    description: Optional[str] = None
    status: str = "active"


class QueueItemRead(BaseModel):
    """Queue item as returned to the v1 UI.

    Field names match v1 ``agent_queue.QueueItem`` exactly (``project``,
    not ``project_id``; ``agent``, not ``agent_id``) so the vendored
    queue UI works without rewrites.
    """

    id: str
    title: str
    description: str = ""
    column: str = "queued"
    project: Optional[str] = None
    complexity: str = "medium"
    agent: Optional[str] = None
    doc_path: Optional[str] = None
    session_id: Optional[str] = None
    session_status: Optional[str] = None
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class QueueItemCreate(BaseModel):
    """Create-payload for ``POST /api/queue``."""

    title: str
    description: Optional[str] = ""
    column: Optional[str] = "queued"
    project: Optional[str] = None
    complexity: Optional[str] = "medium"
    agent: Optional[str] = None
    doc_path: Optional[str] = None
    notes: Optional[str] = ""
    tags: list[str] = Field(default_factory=list)
    priority: Optional[int] = 0


class QueueItemUpdate(BaseModel):
    """Partial-update payload for ``PATCH /api/queue/{id}``."""

    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    project: Optional[str] = None
    complexity: Optional[str] = None
    agent: Optional[str] = None
    doc_path: Optional[str] = None
    session_id: Optional[str] = None
    session_status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    priority: Optional[int] = None


class DispatchRequest(BaseModel):
    """Body of ``POST /api/queue/{id}/dispatch``."""

    agent_id: str = Field(..., min_length=1)
    custom_prompt: Optional[str] = None


class DispatchAutoRequest(BaseModel):
    """Body of ``POST /api/queue/{id}/dispatch/auto`` (no fields, kept for symmetry)."""


class DispatchStatus(BaseModel):
    """Dispatch job row as returned by the API.

    Timestamps are declared as :class:`datetime` so Pydantic serializes
    them to ISO-8601 strings on the wire while still accepting raw ORM
    datetime values via ``from_attributes``.
    """

    id: str
    queue_item_id: str
    agent_id: str
    status: str
    run_id: Optional[str] = None
    task_prompt: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class QueueStats(BaseModel):
    """Aggregate counts returned by ``GET /api/queue``."""

    total: int
    urgent: int = 0
    active: int = 0
    review: int = 0
    queued: int = 0
    ideas: int = 0
    running_sessions: int = 0


class QueueOverview(BaseModel):
    """Full queue snapshot used by the v1 UI."""

    items: list[QueueItemRead]
    by_column: dict[str, list[QueueItemRead]]
    stats: QueueStats
