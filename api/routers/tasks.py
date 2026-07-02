"""Task and focus API routes.

**Project-Box is canonical.** ``GET``/``POST /api/tasks`` read and create
via Project-Box (Obsidian vault). Legacy ``kanban.tasks`` CRUD remains for
historical UUID rows only — new work should use ``/api/projectbox/tasks``.

Focus mode resolves tasks by Project-Box filename and logs time entries on
stop via ``POST /api/tasks/{id}/time`` upstream.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from schemas.projectbox import ProjectBoxTaskUpdate
from schemas.task import FocusSessionStart, QuickTask, TaskReorder, TaskUpdate
from services import focus_service, projectbox_client, task_service
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])

DEPRECATION = (
    "Legacy kanban.tasks API — use /api/projectbox/tasks "
    "(Project-Box replaced Kanban)."
)


def _is_projectbox_id(task_id: str) -> bool:
    """Project-Box ids are vault filenames (typically ``*.md``)."""
    return task_id.endswith(".md") or "/" not in task_id and "." in task_id


# ---------------------------------------------------------------------------
# Project-Box-backed task surface (canonical)
# ---------------------------------------------------------------------------


@router.get("/api/tasks")
async def get_tasks() -> dict[str, Any]:
    """List tasks from Project-Box (replaces legacy Kanban list)."""
    try:
        tasks = await projectbox_client.list_tasks()
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "source": "projectbox",
    }


@router.post("/api/tasks", status_code=201)
async def create_task(task_data: QuickTask) -> dict[str, Any]:
    """Create a task in Project-Box."""
    try:
        task = await projectbox_client.create_task(task_data.title)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    payload = task.model_dump(mode="json")
    payload["source"] = "projectbox"
    return payload


@router.put("/api/tasks/{task_id:path}")
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
) -> dict[str, Any]:
    """Update a Project-Box task when ``task_id`` is a vault filename."""
    if not _is_projectbox_id(task_id):
        raise HTTPException(
            status_code=410,
            detail=DEPRECATION,
        )
    mapping = ProjectBoxTaskUpdate(
        title=task_update.title,
        status=_map_column_to_status(task_update.column),
    )
    try:
        task = await projectbox_client.update_task(task_id, mapping)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=str(exc),
        )
    return task.model_dump(mode="json")


def _map_column_to_status(column: str | None) -> str | None:
    """Best-effort Kanban column → Project-Box status."""
    if column is None:
        return None
    col = column.lower()
    if col in {"done", "archive"}:
        return "done"
    if col in {"inprogress", "in-progress", "active", "focus"}:
        return "in-progress"
    if col in {"unsorted", "today", "queued", "open"}:
        return "open"
    return "open"


# ---------------------------------------------------------------------------
# Legacy kanban.tasks (UUID rows only — deprecated)
# ---------------------------------------------------------------------------


@router.post("/api/tasks/reorder")
async def reorder_tasks(
    reorder_data: TaskReorder,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Reorder a legacy kanban task (deprecated)."""
    if _is_projectbox_id(reorder_data.task_id):
        raise HTTPException(
            status_code=400,
            detail="Reorder is not supported for Project-Box tasks.",
        )
    result = await task_service.reorder(session, reorder_data)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/api/tasks/column/{column}")
async def delete_column_tasks(
    column: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete all tasks in a legacy kanban column (deprecated)."""
    deleted = await task_service.clear_column(session, column)
    return {"deleted": deleted, "column": column, "deprecated": True}


@router.delete("/api/tasks/{task_id:path}")
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Archive a Project-Box task or delete a legacy kanban row."""
    if _is_projectbox_id(task_id):
        try:
            result = await projectbox_client.archive_task(task_id)
        except ProjectBoxOffline as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=str(exc),
            )
        return result

    deleted = await task_service.remove(session, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True, "deprecated": True}


@router.post("/api/tasks/{task_id}/to-kanban")
async def task_to_kanban(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Legacy kanban helper (deprecated)."""
    raise HTTPException(status_code=410, detail=DEPRECATION)


@router.post("/api/tasks/{task_id}/snooze")
async def snooze_task(
    task_id: str,
    snooze_data: dict,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Snooze a legacy kanban task (deprecated — use /api/briefing/snoozes)."""
    if _is_projectbox_id(task_id):
        raise HTTPException(
            status_code=400,
            detail="Snooze Project-Box tasks via /api/briefing/snoozes.",
        )
    hours = float(snooze_data.get("hours", 1))
    wake_at = await task_service.snooze(session, task_id, hours=hours)
    if wake_at is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"snoozed": True, "wake_at": wake_at, "deprecated": True}


# ---------------------------------------------------------------------------
# Focus (Project-Box task ids)
# ---------------------------------------------------------------------------


@router.post("/api/focus/start")
async def start_focus(focus_data: FocusSessionStart) -> dict[str, Any]:
    """Start focus mode on a Project-Box task."""
    session_data = await focus_service.start(focus_data)
    if session_data is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return session_data


@router.post("/api/focus/stop")
async def stop_focus() -> dict[str, Any]:
    """End focus mode and log time to Project-Box when possible."""
    return await focus_service.stop()


@router.get("/api/focus/status")
async def get_focus_status() -> dict[str, Any]:
    """Get current focus session."""
    return await focus_service.status()
