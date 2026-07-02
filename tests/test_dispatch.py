"""Dispatch state-machine tests (Sprint 2).

The OpenClaw client is mocked so the suite never needs a live Synapse
gateway. The "offline" path is exercised end-to-end via the real
``send_to_agent`` (which returns ``offline=True`` when
``MOLTBOT_GATEWAY_WS_URL`` is unset).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.agents import DispatchJob, QueueItem
from schemas.queue import QueueItemRead, QueueItemUpdate
from scripts import queue_worker
from services import openclaw_client
from services.openclaw_client import DispatchResult
from services import queue_service
from services.queue_service import suggest_agent_for_item


@pytest.fixture(autouse=True)
def _ensure_offline_mode() -> None:
    """Defensive: tests must never accidentally hit a real gateway."""
    previous = os.environ.get(openclaw_client.GATEWAY_WS_URL_ENV)
    os.environ[openclaw_client.GATEWAY_WS_URL_ENV] = ""
    yield
    if previous is not None:
        os.environ[openclaw_client.GATEWAY_WS_URL_ENV] = previous
    else:
        os.environ.pop(openclaw_client.GATEWAY_WS_URL_ENV, None)


@pytest.mark.integration
async def test_dispatch_offline_marks_item_pending(app_client: AsyncClient) -> None:
    """With no gateway URL, dispatch returns offline=True and item flips to active."""
    created = (
        await app_client.post("/api/queue", json={"title": "smoke dispatch"})
    ).json()

    response = await app_client.post(
        f"/api/queue/{created['id']}/dispatch",
        json={"agent_id": "jarvis"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["offline"] is True
    assert body["run_id"] is None
    assert body["agent_id"] == "jarvis"

    after = (await app_client.get(f"/api/queue/{created['id']}")).json()
    assert after["column"] == "active"
    assert after["session_status"] == "pending"
    assert after["agent"] == "jarvis"


@pytest.mark.integration
async def test_dispatch_unknown_agent_returns_400(app_client: AsyncClient) -> None:
    """An agent not in the registry should reject dispatch with HTTP 400."""
    created = (
        await app_client.post("/api/queue", json={"title": "bad agent"})
    ).json()
    response = await app_client.post(
        f"/api/queue/{created['id']}/dispatch",
        json={"agent_id": "no-such-agent"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["job_id"].startswith("dj_")

    history = (
        await app_client.get(f"/api/queue/{created['id']}/status")
    ).json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["agent_id"] == "no-such-agent"


@pytest.mark.integration
async def test_dispatch_404_for_unknown_item(app_client: AsyncClient) -> None:
    """Dispatch against a missing queue id returns 404."""
    response = await app_client.post(
        "/api/queue/q_does_not_exist/dispatch",
        json={"agent_id": "jarvis"},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_dispatch_auto_uses_router(app_client: AsyncClient) -> None:
    """Auto-route picks an agent from tags; offline path still succeeds."""
    created = (
        await app_client.post(
            "/api/queue",
            json={"title": "venture growth analysis", "tags": ["research"]},
        )
    ).json()
    response = await app_client.post(f"/api/queue/{created['id']}/dispatch/auto")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "aria"
    assert body["offline"] is True


@pytest.mark.integration
async def test_dispatch_records_status_history(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Each dispatch attempt persists a row in ``agents.dispatch_jobs``."""
    created = (
        await app_client.post("/api/queue", json={"title": "history test"})
    ).json()
    await app_client.post(
        f"/api/queue/{created['id']}/dispatch", json={"agent_id": "jarvis"}
    )

    history = (
        await app_client.get(f"/api/queue/{created['id']}/status")
    ).json()
    assert len(history) == 1
    assert history[0]["queue_item_id"] == created["id"]
    assert history[0]["agent_id"] == "jarvis"


@pytest.mark.integration
async def test_dispatch_online_path_runs_full_state_machine(
    app_client: AsyncClient,
) -> None:
    """Patch the openclaw client to simulate a Synapse-accepted run."""
    created = (
        await app_client.post("/api/queue", json={"title": "online happy path"})
    ).json()

    with patch.object(
        openclaw_client,
        "send_to_agent",
        AsyncMock(return_value=DispatchResult(success=True, run_id="run-xyz")),
    ), patch.object(openclaw_client, "gateway_url", return_value="ws://fake"):
        response = await app_client.post(
            f"/api/queue/{created['id']}/dispatch",
            json={"agent_id": "jarvis"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["offline"] is False
    assert body["run_id"] == "run-xyz"

    after = (await app_client.get(f"/api/queue/{created['id']}")).json()
    assert after["session_id"] == "run-xyz"
    assert after["session_status"] == "running"
    assert after["column"] == "active"


@pytest.mark.integration
async def test_worker_prioritizes_urgent_before_queued(
    db_session: AsyncSession,
) -> None:
    """Urgent queue items dispatch before higher-priority normal queued work."""
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            QueueItem(
                id="q_queued",
                title="queued",
                column="queued",
                complexity="medium",
                priority=100,
                tags=[],
                notes="",
                created_at=now,
                updated_at=now,
            ),
            QueueItem(
                id="q_urgent",
                title="urgent",
                column="urgent",
                complexity="medium",
                priority=0,
                tags=[],
                notes="",
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    await db_session.flush()

    routed = await queue_worker.route_items(db_session, dry_run=True)
    assert [item["id"] for item in routed] == ["q_urgent", "q_queued"]


@pytest.mark.integration
async def test_worker_archives_old_review_done_items(
    db_session: AsyncSession,
) -> None:
    """Completed review items age into archive."""
    now = datetime.now(timezone.utc)
    item = QueueItem(
        id="q_review_done",
        title="review done",
        column="review",
        complexity="medium",
        session_status="done",
        priority=0,
        tags=[],
        notes="",
        completed_at=now - timedelta(days=8),
        created_at=now - timedelta(days=9),
        updated_at=now - timedelta(days=8),
    )
    db_session.add(item)
    await db_session.flush()

    archived = await queue_worker.archive_old_done(
        db_session,
        dry_run=False,
        now=now,
    )
    await db_session.refresh(item)

    assert [entry["id"] for entry in archived] == ["q_review_done"]
    assert item.column == "archive"


@pytest.mark.integration
async def test_active_task_update_marks_needs_update(
    db_session: AsyncSession,
) -> None:
    """Prompt-affecting edits to active work are picked up by the worker."""
    now = datetime.now(timezone.utc)
    item = QueueItem(
        id="q_update",
        title="old title",
        column="active",
        complexity="medium",
        session_id="run-old",
        session_status="running",
        agent_id="jarvis",
        priority=0,
        tags=[],
        notes="",
        created_at=now,
        updated_at=now,
    )
    db_session.add(item)
    await db_session.flush()

    updated = await queue_service.update(
        db_session,
        item.id,
        QueueItemUpdate(title="new title"),
    )

    assert updated is not None
    assert updated.session_status == "needs_update"


@pytest.mark.integration
async def test_worker_dispatches_needs_update_items(
    db_session: AsyncSession,
) -> None:
    """Active items marked needs_update get a fresh dispatch."""
    now = datetime.now(timezone.utc)
    item = QueueItem(
        id="q_needs_update",
        title="needs update",
        column="active",
        complexity="medium",
        session_id="run-old",
        session_status="needs_update",
        agent_id="jarvis",
        priority=0,
        tags=[],
        notes="",
        created_at=now,
        updated_at=now,
    )
    db_session.add(item)
    await db_session.flush()

    with patch.object(
        openclaw_client,
        "send_to_agent",
        AsyncMock(return_value=DispatchResult(success=True, run_id="run-new")),
    ):
        retried = await queue_worker.retry_pending_items(db_session, dry_run=False)

    await db_session.refresh(item)
    assert retried[0]["run_id"] == "run-new"
    assert item.session_id == "run-new"
    assert item.session_status == "running"


@pytest.mark.integration
async def test_gateway_connection_failure_queues_offline() -> None:
    """A configured but unreachable gateway is retryable offline work."""
    with patch.object(openclaw_client, "gateway_url", return_value="ws://fake"):
        if openclaw_client.websockets is None:
            result = await openclaw_client.send_to_agent("jarvis", "prompt")
        else:
            with patch.object(
                openclaw_client.websockets,
                "connect",
                side_effect=OSError("down"),
            ):
                result = await openclaw_client.send_to_agent("jarvis", "prompt")

    assert result.success is True
    assert result.offline is True


def test_suggest_agent_routing_table() -> None:
    """Tag-based routing matches v1 ``task_dispatch.get_agent_for_task``."""
    def make(tags: list[str], title: str = "") -> QueueItemRead:
        return QueueItemRead(id="q_x", title=title, tags=tags)

    assert suggest_agent_for_item(make(["research"])) == "aria"
    assert suggest_agent_for_item(make(["finance"])) == "peter"
    assert suggest_agent_for_item(make(["medical"])) == "watson"
    assert suggest_agent_for_item(make(["venture", "bd"])) == "jc"
    assert suggest_agent_for_item(make(["venture"])) == "willb"
    assert suggest_agent_for_item(make(["startup"])) == "elon"
    assert suggest_agent_for_item(make([], title="random work")) == "jarvis"
