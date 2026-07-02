"""Async HTTP client for the Project-Box (Flow Focus) API.

Treats Project-Box as an *immutable* external service: this module never
mutates Project-Box source code, never reads its Markdown files directly,
and is tolerant of the service being offline (the queue/dispatch client
ships the same offline pattern — see :mod:`services.openclaw_client`).

Usage::

    tasks = await projectbox_client.list_tasks()
    task  = await projectbox_client.create_task("Investigate flaky deploy")
    task  = await projectbox_client.update_task(task.id, status="done")
    await projectbox_client.archive_task(task.id)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

from cache import projectbox_cache
from config import get_settings
from schemas.projectbox import (
    ProjectBoxTask,
    ProjectBoxTaskUpdate,
    ProjectBoxTimeEntryCreate,
)

logger = logging.getLogger(__name__)


class ProjectBoxOffline(RuntimeError):
    """Raised when Project-Box is configured but unreachable.

    Callers should catch this and either return a graceful fallback
    (briefing stale block returns empty, email-to-task records an offline
    flag) or surface a 503 to the user.
    """


def _base_url() -> Optional[str]:
    """Return the configured Project-Box base URL or ``None`` to opt out."""
    url = (get_settings().projectbox_url or "").rstrip("/")
    return url or None


def _timeout_seconds() -> float:
    return float(get_settings().projectbox_timeout_seconds)


def is_configured() -> bool:
    """``True`` when a Project-Box URL is set (regardless of reachability)."""
    return _base_url() is not None


async def _request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
) -> Any:
    """Helper around ``httpx.AsyncClient`` with consistent timeouts/logging."""
    base = _base_url()
    if base is None:
        raise ProjectBoxOffline("Project-Box URL not configured")

    url = f"{base}{path}"
    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            response = await client.request(method, url, json=json_body)
    except httpx.HTTPError as exc:
        logger.warning("projectbox_client: %s %s failed: %s", method, url, exc)
        raise ProjectBoxOffline(str(exc)) from exc

    if response.status_code >= 500:
        raise ProjectBoxOffline(
            f"Project-Box {method} {path} -> {response.status_code}: "
            f"{response.text[:200]}"
        )
    if response.status_code >= 400:
        # 4xx is a client-side problem (e.g. PUT against a missing file).
        # Surface the body so the FastAPI router can repackage it.
        try:
            detail = response.json().get("error", response.text)
        except (ValueError, json.JSONDecodeError):
            detail = response.text
        raise httpx.HTTPStatusError(
            f"Project-Box {method} {path} -> {response.status_code}: {detail}",
            request=response.request,
            response=response,
        )

    if not response.text:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def health() -> dict[str, Any]:
    """Cheap probe: ``GET /api/tasks`` and report basic counts."""
    base = _base_url()
    if base is None:
        return {"configured": False, "reachable": False, "url": None}
    try:
        payload = await _request("GET", "/api/tasks")
    except ProjectBoxOffline as exc:
        return {
            "configured": True,
            "reachable": False,
            "url": base,
            "detail": str(exc),
        }
    return {
        "configured": True,
        "reachable": True,
        "url": base,
        "task_count": len(payload) if isinstance(payload, list) else 0,
    }


async def list_tasks(*, use_cache: bool = True) -> list[ProjectBoxTask]:
    """Return every task currently in the Obsidian Tasks folder.

    Uses the short-TTL Redis cache by default; callers needing the
    freshest data (e.g. immediately after a write) should pass
    ``use_cache=False`` *or* invalidate the cache via
    :func:`cache.projectbox_cache.invalidate`.
    """
    raw: Optional[list[Any]] = None
    if use_cache:
        raw = await projectbox_cache.load_list()
    if raw is None:
        fresh = await _request("GET", "/api/tasks")
        if not isinstance(fresh, list):
            return []
        raw = fresh
        await projectbox_cache.store_list(raw)

    tasks: list[ProjectBoxTask] = []
    for row in raw:
        try:
            tasks.append(ProjectBoxTask.model_validate(row))
        except Exception:  # pragma: no cover — defensive against ad-hoc YAML
            logger.warning("projectbox_client: skipping malformed task row")
    return tasks


async def get_task(task_id: str) -> Optional[ProjectBoxTask]:
    """Fetch a single task by filename. Returns ``None`` if absent.

    Project-Box's list endpoint is the canonical fetch path (no
    ``GET /api/tasks/{id}`` exists upstream), so we fetch-all and filter.
    Acceptable because the vault is bounded by an order of hundreds.
    """
    tasks = await list_tasks()
    return next((t for t in tasks if t.id == task_id), None)


async def create_task(title: str) -> ProjectBoxTask:
    """Create a new Project-Box task by title."""
    payload = await _request("POST", "/api/tasks", json_body={"title": title})
    await projectbox_cache.invalidate()
    return ProjectBoxTask.model_validate(payload)


async def update_task(
    task_id: str, updates: ProjectBoxTaskUpdate
) -> ProjectBoxTask:
    """Apply a partial update; Project-Box rewrites the Markdown file."""
    existing = await get_task(task_id)
    if existing is None:
        raise httpx.HTTPStatusError(
            f"Project-Box task {task_id} not found",
            request=httpx.Request("PUT", task_id),
            response=httpx.Response(404),
        )

    # Merge existing + patch so Project-Box's "rewrite whole frontmatter"
    # semantics don't silently drop unspecified fields.
    merged = existing.model_dump(mode="json")
    merged.update(updates.to_projectbox_payload())
    payload = await _request(
        "PUT", f"/api/tasks/{_encode(task_id)}", json_body=merged
    )
    await projectbox_cache.invalidate()
    return ProjectBoxTask.model_validate(payload)


async def archive_task(task_id: str) -> dict[str, Any]:
    """Archive (move to ``Archive/``) a Project-Box task by filename."""
    result = await _request("DELETE", f"/api/tasks/{_encode(task_id)}")
    await projectbox_cache.invalidate()
    return result


async def add_time_entry(
    task_id: str, entry: ProjectBoxTimeEntryCreate
) -> dict[str, Any]:
    """Append a focus-timer entry to a task's frontmatter."""
    result = await _request(
        "POST",
        f"/api/tasks/{_encode(task_id)}/time",
        json_body=entry.model_dump(mode="json"),
    )
    await projectbox_cache.invalidate()
    return result


def _encode(task_id: str) -> str:
    """URL-encode the filename so spaces / special chars survive transit."""
    return quote(task_id, safe="")
