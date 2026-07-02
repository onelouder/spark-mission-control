"""Subscriber + run-status-event tests (Sprint 2)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import DispatchJob, QueueItem
from repositories import dispatch_repo
from services import dispatch_service, dispatch_subscriber, openclaw_client


@pytest.fixture(autouse=True)
def _clear_gateway_env() -> None:
    """Keep the suite deterministic regardless of host env."""
    previous = os.environ.get(openclaw_client.GATEWAY_WS_URL_ENV)
    os.environ[openclaw_client.GATEWAY_WS_URL_ENV] = ""
    yield
    if previous is not None:
        os.environ[openclaw_client.GATEWAY_WS_URL_ENV] = previous
    else:
        os.environ.pop(openclaw_client.GATEWAY_WS_URL_ENV, None)


async def _insert_running_item(
    session: AsyncSession, *, item_id: str, run_id: str
) -> tuple[QueueItem, DispatchJob]:
    """Seed a queue item + dispatched DispatchJob in the running state."""
    now = datetime.now(timezone.utc)
    item = QueueItem(
        id=item_id,
        title="subscriber test",
        column="active",
        complexity="medium",
        session_id=run_id,
        session_status="running",
        agent_id="jarvis",
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    await session.flush()
    job = await dispatch_repo.create(
        session,
        queue_item_id=item.id,
        agent_id="jarvis",
        task_prompt="test prompt",
    )
    await dispatch_repo.mark_dispatched(session, job, run_id=run_id)
    return item, job


@pytest.mark.integration
async def test_run_status_completed_transitions_item_to_review(
    db_session: AsyncSession,
) -> None:
    """A ``run.status=completed`` event flips the queue item to review."""
    item, job = await _insert_running_item(
        db_session, item_id="q_sub_001", run_id="run-1"
    )
    await db_session.flush()

    updated_job = await dispatch_service.apply_run_status_event(
        db_session,
        {"topic": "run.status", "payload": {"runId": "run-1", "status": "completed"}},
    )
    assert updated_job is not None
    assert updated_job.status == "completed"

    await db_session.refresh(item)
    assert item.column == "review"
    assert item.session_status == "done"
    assert item.completed_at is not None


@pytest.mark.integration
async def test_run_status_failed_marks_job_failed(db_session: AsyncSession) -> None:
    """A ``failed`` event marks the dispatch job and queue item failed."""
    item, _ = await _insert_running_item(
        db_session, item_id="q_sub_002", run_id="run-2"
    )
    await db_session.flush()
    job = await dispatch_service.apply_run_status_event(
        db_session,
        {"payload": {"runId": "run-2", "status": "failed", "error": "boom"}},
    )
    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "boom"

    await db_session.refresh(item)
    assert item.session_status == "failed"


@pytest.mark.integration
async def test_superseded_run_status_does_not_complete_current_item(
    db_session: AsyncSession,
) -> None:
    """Late events from an old run should not move a redispatched item."""
    item, _ = await _insert_running_item(
        db_session,
        item_id="q_sub_superseded",
        run_id="run-old",
    )
    item.session_id = "run-new"
    item.session_status = "running"
    await db_session.flush()

    job = await dispatch_service.apply_run_status_event(
        db_session,
        {"payload": {"runId": "run-old", "status": "completed"}},
    )

    assert job is not None
    assert job.status == "completed"
    await db_session.refresh(item)
    assert item.column == "active"
    assert item.session_id == "run-new"
    assert item.session_status == "running"
    assert item.completed_at is None


@pytest.mark.integration
async def test_run_status_ignores_unknown_run_id(db_session: AsyncSession) -> None:
    """Events for run-ids we never dispatched are silently dropped."""
    job = await dispatch_service.apply_run_status_event(
        db_session,
        {"payload": {"runId": "run-never-issued", "status": "completed"}},
    )
    assert job is None


def test_start_in_lifespan_is_offline_no_op() -> None:
    """Without a gateway URL, the subscriber starter returns ``None``."""
    assert openclaw_client.gateway_url() is None
    task = dispatch_subscriber.start_in_lifespan()
    assert task is None


@pytest.mark.integration
async def test_subscriber_loop_starts_and_cancels() -> None:
    """Subscriber respects cancellation and never raises on shutdown."""

    async def fake_stream():
        yield {"payload": {"runId": "noop", "status": "completed"}}
        # Hang so the task survives long enough to be cancelled.
        await asyncio.Event().wait()

    with patch.object(
        openclaw_client, "subscribe_run_updates", lambda: fake_stream()
    ), patch.object(openclaw_client, "gateway_url", return_value="ws://fake"):
        task = asyncio.create_task(dispatch_subscriber.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
