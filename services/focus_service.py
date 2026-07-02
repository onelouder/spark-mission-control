"""Focus-mode session backed by Redis, tasks resolved via Project-Box.

The legacy focus flow validated tasks against ``kanban.tasks`` UUIDs.
Project-Box is now canonical: ``task_id`` is the Obsidian filename
(e.g. ``"Pay taxes.md"``). On stop, elapsed time is appended to the
task's ``timeEntries`` frontmatter via Project-Box's API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from cache import focus_cache
from schemas.projectbox import ProjectBoxTimeEntryCreate
from schemas.task import FocusSessionStart
from services import projectbox_client
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)


async def start(data: FocusSessionStart) -> Optional[dict[str, Any]]:
    """Start focus on a Project-Box task; return session dict or ``None``."""
    task = await projectbox_client.get_task(data.task_id)
    if task is None:
        return None

    session_data = {
        "task_id": task.id,
        "task_title": task.title,
        "started_at": data.started_at,
        "mode": data.mode,
        "source": "projectbox",
    }
    await focus_cache.save_session(session_data)
    return session_data


async def stop() -> dict[str, Any]:
    """End focus; log a time entry on the Project-Box task when possible."""
    session = await focus_cache.get_session()
    await focus_cache.clear_session()

    logged = False
    if session and session.get("source") == "projectbox":
        logged = await _log_time_entry(session)

    return {"stopped": True, "time_logged": logged}


async def status() -> dict[str, Any]:
    """Return the active session with elapsed/remaining fields."""
    session = await focus_cache.get_session()
    if session is None:
        return {"session": None}
    enriched = await focus_cache.enrich_status(session)
    return {"session": enriched}


async def _log_time_entry(session: dict[str, Any]) -> bool:
    """Append a focus interval to Project-Box; swallow offline errors."""
    task_id = session.get("task_id")
    started_at = session.get("started_at")
    if not task_id or not started_at:
        return False

    end = datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("focus_service: bad started_at %r", started_at)
        return False

    entry = ProjectBoxTimeEntryCreate(
        startTime=start,
        endTime=end,
        description=f"Focus ({session.get('mode', 'session')})",
    )
    try:
        await projectbox_client.add_time_entry(task_id, entry)
        return True
    except ProjectBoxOffline as exc:
        logger.warning(
            "focus_service: Project-Box offline; time not logged (%s)", exc
        )
        return False
    except Exception:
        logger.exception("focus_service: failed to log time entry")
        return False
