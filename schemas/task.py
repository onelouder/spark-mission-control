"""Pydantic DTOs for Kanban tasks (API layer only)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TaskRead(BaseModel):
    """Task as returned to the frontend (v1-compatible shape)."""

    id: str
    title: str
    description: str = ""
    column: str
    position: int = 0
    energy: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    stuck_since: Optional[str] = None
    snoozed_until: Optional[str] = None
    show_in_briefing: Optional[bool] = True
    project_id: Optional[str] = None
    context_id: Optional[str] = None
    flow_state: Optional[str] = "normal"
    blocked_reason: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class TaskUpdate(BaseModel):
    """Partial task update."""

    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    energy: Optional[str] = None
    notes: Optional[str] = None
    position: Optional[int] = None


class TaskReorder(BaseModel):
    """Drag-and-drop reorder payload."""

    task_id: str
    column: str
    position: int


class QuickTask(BaseModel):
    """Create task from quick-add."""

    title: str
    column: Optional[str] = "unsorted"


class FocusSessionStart(BaseModel):
    """Start focus mode."""

    task_id: str
    started_at: str
    mode: str = "pomodoro"


class FocusSessionRead(BaseModel):
    """Active focus session."""

    task_id: str
    task_title: str
    started_at: str
    mode: str
    elapsed_seconds: Optional[int] = None
    remaining_seconds: Optional[int] = None
