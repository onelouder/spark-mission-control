"""Dispatch a queue item to an OpenClaw agent.

Owns the :class:`DispatchJob` state machine and decides what to write
back onto the corresponding :class:`QueueItem` after a successful (or
failed) dispatch. The actual wire-protocol lives in
:mod:`services.openclaw_client`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import DispatchJob
from repositories import dispatch_repo, queue_repo
from services import openclaw_client

logger = logging.getLogger(__name__)


@dataclass
class DispatchOutcome:
    """Service-level result so the router can produce a friendly response."""

    success: bool
    job: DispatchJob
    run_id: Optional[str]
    offline: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def build_prompt(
    *, title: str, description: str, doc_path: Optional[str], notes: str
) -> str:
    """Render the canonical task prompt v1's ``_build_task_prompt`` produced.

    Kept in this module so the prompt format is the single source of truth
    for both API-facing previews and the actual dispatch wire payload.
    """
    parts = [f"## Task: {title}", ""]
    if description:
        parts.extend([description, ""])
    if doc_path:
        parts.extend([f"Reference doc: {doc_path}", ""])
    if notes:
        recent = notes[-500:] if len(notes) > 500 else notes
        parts.extend([f"Previous notes:\n{recent}", ""])
    parts.extend(
        [
            "Work on this task. When complete or blocked, update the notes "
            "with your progress.",
            "If you need to spawn a sub-agent for part of the work, do so.",
        ]
    )
    return "\n".join(parts)


async def dispatch(
    session: AsyncSession,
    *,
    queue_item_id: str,
    agent_id: str,
    custom_prompt: Optional[str] = None,
) -> Optional[DispatchOutcome]:
    """Dispatch a queue item to ``agent_id``.

    The flow is:
        1. Load the queue item (return ``None`` if missing).
        2. Validate the agent against
           :data:`services.openclaw_client.AGENT_REGISTRY`.
        3. Insert a ``pending`` :class:`DispatchJob`.
        4. Hand the rendered prompt to :func:`openclaw_client.send_to_agent`.
        5. Update the job + queue-item with the result.

    Returns ``None`` if the queue item does not exist. Otherwise the
    :class:`DispatchOutcome` distinguishes:

    - ``success=True, offline=False`` — gateway acked the run.
    - ``success=True, offline=True``  — gateway not configured; the queue
      item is left in ``column='active'`` with ``session_status='pending'``.
      A later run can re-dispatch the same item.
    - ``success=False`` — gateway rejected the request; queue item is
      reverted and the job marked failed.
    """
    item = await queue_repo.get_item(session, queue_item_id)
    if item is None:
        return None

    if not openclaw_client.is_known_agent(agent_id):
        job = await dispatch_repo.create(
            session,
            queue_item_id=queue_item_id,
            agent_id=agent_id,
            task_prompt=None,
            payload={},
        )
        await dispatch_repo.mark_completed(
            session, job, error=f"unknown agent: {agent_id}"
        )
        return DispatchOutcome(
            success=False,
            job=job,
            run_id=None,
            offline=False,
            error=f"unknown agent: {agent_id}",
        )

    prompt = custom_prompt or build_prompt(
        title=item.title,
        description=item.description or "",
        doc_path=item.doc_path,
        notes=item.notes or "",
    )

    job = await dispatch_repo.create(
        session,
        queue_item_id=queue_item_id,
        agent_id=agent_id,
        task_prompt=prompt,
        payload={"agent_id": agent_id},
    )

    result = await openclaw_client.send_to_agent(agent_id, prompt)

    if result.success and not result.offline:
        await dispatch_repo.mark_dispatched(session, job, run_id=result.run_id)
        item.column = "active"
        item.session_id = result.run_id
        item.session_status = "running"
        item.agent_id = agent_id
        item.notes = _append_note(
            item.notes or "",
            f"Dispatched to {agent_id} (run: {(result.run_id or '?')[:8]})",
        )
        item.updated_at = datetime.now(timezone.utc)
    elif result.success and result.offline:
        item.column = "active"
        item.session_id = None
        item.session_status = "pending"
        item.agent_id = agent_id
        item.notes = _append_note(
            item.notes or "",
            f"Queued for {agent_id} (gateway offline)",
        )
        item.updated_at = datetime.now(timezone.utc)
    else:
        await dispatch_repo.mark_completed(session, job, error=result.error)

    await session.flush()
    return DispatchOutcome(
        success=result.success,
        job=job,
        run_id=result.run_id,
        offline=result.offline,
        error=result.error,
    )


async def apply_run_status_event(
    session: AsyncSession, event: dict
) -> Optional[DispatchJob]:
    """Apply a Synapse ``run.status`` event to the matching DispatchJob.

    Accepts the event payload v1 emitted, e.g.::

        {"topic": "run.status",
         "payload": {"runId": "abc", "status": "completed"}}

    Unknown ``run_id``s are ignored (logged at DEBUG).
    """
    payload = event.get("payload") or event
    run_id = payload.get("runId") or payload.get("run_id")
    status = payload.get("status")
    if not run_id or not status:
        return None

    job = await dispatch_repo.get_by_run_id(session, run_id)
    if job is None:
        logger.debug("apply_run_status_event: no job for run_id=%s", run_id)
        return None

    item = await queue_repo.get_item(session, job.queue_item_id)
    item_is_current = item is not None and item.session_id == run_id
    if status == "running":
        await dispatch_repo.mark_running(session, job)
        if item_is_current:
            item.session_status = "running"
    elif status in {"completed", "succeeded", "done"}:
        await dispatch_repo.mark_completed(session, job)
        if item_is_current:
            item.session_status = "done"
            item.column = "review"
            item.completed_at = datetime.now(timezone.utc)
    elif status in {"failed", "error"}:
        await dispatch_repo.mark_completed(
            session, job, error=str(payload.get("error") or "agent reported failure")
        )
        if item_is_current:
            item.session_status = "failed"

    await session.flush()
    return job


def _append_note(existing: str, new_note: str) -> str:
    """Append a timestamped note line to the queue item's notes field."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"{existing}\n---\n[{stamp}] {new_note}".lstrip()
