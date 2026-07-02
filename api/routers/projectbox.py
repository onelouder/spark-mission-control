"""Thin proxy router exposing Project-Box through Mission Control v2.

Why proxy at all? Three reasons:

1. Mission Control v2 already owns the authenticated session boundary
   (P1 lands later); routing tasks through this layer means we add auth
   in one place rather than punching a hole through to port 5173.
2. v2's structured access log + tracing picks up Project-Box calls so
   we get a single timeline when investigating a slow request.
3. Tooling (briefing, email→task) talks to ``projectbox_client``
   directly; the proxy is purely for browser/CLI clients that want a
   uniform ``http://mc2/api/*`` surface.

The endpoints intentionally mirror Project-Box's REST shape — no field
renaming, no Pydantic coercion of the response — so a future migration
to a direct Project-Box embed is mechanical.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from schemas.projectbox import (
    ProjectBoxStatus,
    ProjectBoxTask,
    ProjectBoxTaskCreate,
    ProjectBoxTaskUpdate,
    ProjectBoxTimeEntryCreate,
)
from services import projectbox_client
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projectbox"])


@router.get("/api/projectbox/health", response_model=ProjectBoxStatus)
async def projectbox_health() -> ProjectBoxStatus:
    """Return whether Project-Box is reachable from this instance."""
    return ProjectBoxStatus.model_validate(await projectbox_client.health())


@router.get("/api/projectbox/tasks", response_model=list[ProjectBoxTask])
async def list_tasks(no_cache: bool = False) -> list[ProjectBoxTask]:
    """Proxy ``GET /api/tasks`` (Redis-cached by default)."""
    try:
        return await projectbox_client.list_tasks(use_cache=not no_cache)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post(
    "/api/projectbox/tasks",
    response_model=ProjectBoxTask,
    status_code=201,
)
async def create_task(payload: ProjectBoxTaskCreate) -> ProjectBoxTask:
    """Proxy ``POST /api/tasks``."""
    try:
        return await projectbox_client.create_task(payload.title)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get(
    "/api/projectbox/tasks/{task_id:path}",
    response_model=ProjectBoxTask,
)
async def get_task(task_id: str) -> ProjectBoxTask:
    """Fetch a single Project-Box task by filename."""
    try:
        task = await projectbox_client.get_task(task_id)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put(
    "/api/projectbox/tasks/{task_id:path}",
    response_model=ProjectBoxTask,
)
async def update_task(
    task_id: str, updates: ProjectBoxTaskUpdate
) -> ProjectBoxTask:
    """Proxy ``PUT /api/tasks/{id}``."""
    try:
        return await projectbox_client.update_task(task_id, updates)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=str(exc),
        )


@router.delete("/api/projectbox/tasks/{task_id:path}")
async def archive_task(task_id: str) -> dict[str, Any]:
    """Proxy ``DELETE /api/tasks/{id}`` (Project-Box archives — never deletes)."""
    try:
        return await projectbox_client.archive_task(task_id)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/api/projectbox/tasks/{task_id:path}/time")
async def add_time_entry(
    task_id: str, entry: ProjectBoxTimeEntryCreate
) -> dict[str, Any]:
    """Append a focus-timer entry to a Project-Box task."""
    try:
        return await projectbox_client.add_time_entry(task_id, entry)
    except ProjectBoxOffline as exc:
        raise HTTPException(status_code=503, detail=str(exc))
