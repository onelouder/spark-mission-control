"""Pydantic DTOs for the Project-Box (Flow Focus) integration.

Project-Box is the immutable, Obsidian-backed task system that replaced
the v1 Mission Control kanban. Each task is a Markdown file in the
``TaskNotes/Tasks`` folder; Project-Box exposes them via a small Express
API on port ``5173``. v2 wraps that API rather than the filesystem so the
Obsidian↔web round-trip stays the single source of truth.

These DTOs mirror the response shape Project-Box emits verbatim — the
``id`` is the filename (e.g. ``"Pay quarterly taxes.md"``), not a UUID.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal["none", "open", "in-progress", "done"]
TaskPriority = Literal["none", "low", "normal", "high"]
TaskQuadrant = Optional[
    Literal["do-first", "schedule", "delegate", "eliminate"]
]


class TimeEntry(BaseModel):
    """A single Project-Box focus-timer log entry."""

    startTime: datetime
    endTime: datetime
    description: str = "Focus session"


class ProjectBoxTask(BaseModel):
    """Project-Box task row as returned by ``GET /api/tasks``."""

    id: str
    title: str
    status: TaskStatus = "none"
    priority: TaskPriority = "normal"
    scheduled: Optional[str] = None
    due: Optional[str] = None
    dateCreated: datetime
    dateModified: datetime
    tags: list[str] = Field(default_factory=list)
    quadrant: TaskQuadrant = None
    completedDate: Optional[str] = None
    timeEstimate: Optional[int] = None
    timeEntries: list[TimeEntry] = Field(default_factory=list)
    pinned: bool = False
    projects: list[str] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    content: str = ""


class ProjectBoxTaskCreate(BaseModel):
    """Body of ``POST /api/tasks`` — Project-Box derives everything else."""

    title: str = Field(..., min_length=1)


class ProjectBoxTaskUpdate(BaseModel):
    """Body of ``PUT /api/tasks/{filename}``.

    Project-Box expects the full frontmatter payload back — we forward
    whatever the caller supplies, defaulting only the fields Project-Box
    requires.
    """

    title: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    scheduled: Optional[str] = None
    due: Optional[str] = None
    dateCreated: Optional[datetime] = None
    dateModified: Optional[datetime] = None
    tags: Optional[list[str]] = None
    quadrant: TaskQuadrant = None
    completedDate: Optional[str] = None
    timeEstimate: Optional[int] = None
    timeEntries: Optional[list[TimeEntry]] = None
    pinned: Optional[bool] = None
    projects: Optional[list[str]] = None
    contexts: Optional[list[str]] = None
    content: Optional[str] = None

    def to_projectbox_payload(self) -> dict[str, Any]:
        """Serialize without ``None`` placeholders Project-Box can't parse."""
        data = self.model_dump(exclude_none=True, mode="json")
        return data


class ProjectBoxTimeEntryCreate(BaseModel):
    """Body of ``POST /api/tasks/{filename}/time``."""

    startTime: datetime
    endTime: datetime
    description: str = "Focus session"


class ProjectBoxStatus(BaseModel):
    """Health probe returned by ``GET /api/projectbox/health``."""

    configured: bool
    reachable: bool
    url: Optional[str] = None
    task_count: Optional[int] = None
    detail: Optional[str] = None
