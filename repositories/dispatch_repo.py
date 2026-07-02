"""Persistence for ``agents.dispatch_jobs``.

A :class:`DispatchJob` is a single attempt to hand a :class:`QueueItem`
off to OpenClaw via Synapse. The state machine is::

    pending --(send)--> dispatched --(ack)--> running
                                    \\
                                     --> failed
    running  --(complete)--> completed
             --(error)----> failed

The :func:`mark_*` helpers below capture every legal transition. Callers
should use them rather than directly mutating ``status``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import DispatchJob


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Generate a dispatch job id (``dj_<uuid4-12>``)."""
    return f"dj_{uuid.uuid4().hex[:12]}"


async def create(
    session: AsyncSession,
    *,
    queue_item_id: str,
    agent_id: str,
    task_prompt: Optional[str] = None,
    payload: Optional[dict] = None,
) -> DispatchJob:
    """Insert a ``pending`` dispatch job for a queue item."""
    job = DispatchJob(
        id=new_id(),
        queue_item_id=queue_item_id,
        agent_id=agent_id,
        status="pending",
        task_prompt=task_prompt,
        payload=payload or {},
        created_at=_utc_now(),
    )
    session.add(job)
    await session.flush()
    return job


async def get(session: AsyncSession, job_id: str) -> Optional[DispatchJob]:
    """Fetch a dispatch job by id."""
    return await session.get(DispatchJob, job_id)


async def get_by_run_id(
    session: AsyncSession, run_id: str
) -> Optional[DispatchJob]:
    """Fetch a dispatch job by its Synapse ``run_id``."""
    result = await session.execute(
        select(DispatchJob).where(DispatchJob.run_id == run_id)
    )
    return result.scalar_one_or_none()


async def list_for_queue_item(
    session: AsyncSession, queue_item_id: str
) -> Sequence[DispatchJob]:
    """Return all dispatch attempts for a queue item, newest first."""
    result = await session.execute(
        select(DispatchJob)
        .where(DispatchJob.queue_item_id == queue_item_id)
        .order_by(DispatchJob.created_at.desc())
    )
    return result.scalars().all()


async def mark_dispatched(
    session: AsyncSession, job: DispatchJob, *, run_id: Optional[str]
) -> DispatchJob:
    """Transition ``pending → dispatched`` and stamp ``run_id``."""
    job.status = "dispatched"
    job.run_id = run_id
    job.dispatched_at = _utc_now()
    await session.flush()
    return job


async def mark_running(session: AsyncSession, job: DispatchJob) -> DispatchJob:
    """Transition ``dispatched → running`` (Synapse acked the run)."""
    job.status = "running"
    await session.flush()
    return job


async def mark_completed(
    session: AsyncSession, job: DispatchJob, *, error: Optional[str] = None
) -> DispatchJob:
    """Transition any state → ``completed``/``failed`` based on ``error``."""
    job.status = "failed" if error else "completed"
    job.error_message = error
    job.completed_at = _utc_now()
    await session.flush()
    return job
