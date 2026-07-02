"""Sprint 3 — briefing assembly + snooze sweep tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cache import briefing_cache
from db.orm.core import Account, EmailTriage
from db.orm.kanban import Task
from services import briefing_service, snooze_service  # noqa: F401


@pytest.fixture(autouse=True)
async def _invalidate_briefing_cache():
    """Stop one test's cached briefing bleeding into the next."""
    await briefing_cache.invalidate()
    yield
    await briefing_cache.invalidate()


@pytest.fixture
async def seed_account(db_session: AsyncSession) -> str:
    """Insert the account FK the EmailTriage rows need."""
    acct = Account(
        id="ops",
        name="Ops Inbox",
        email="ops@example.com",
        provider="gmail",
    )
    db_session.add(acct)
    await db_session.flush()
    await db_session.commit()
    return acct.id


async def _add_email(
    db_session: AsyncSession,
    *,
    email_id: str,
    account_id: str,
    decision: str,
    subject: str,
) -> None:
    row = EmailTriage(
        id=email_id,
        account_id=account_id,
        subject=subject,
        from_address=f"{email_id}@example.com",
        from_name="Sender",
        received_at=datetime.now(timezone.utc),
        final_decision=decision,
        briefing_handled=False,
        converted_to_task=False,
        analysis={},
        pipeline_stages={},
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.commit()


@pytest.mark.integration
async def test_briefing_contains_decisions_and_review_blocks(
    app_client: AsyncClient, db_session: AsyncSession, seed_account: str
) -> None:
    """Decision/review emails surface in their respective briefing blocks."""
    await _add_email(
        db_session,
        email_id="brief-001",
        account_id=seed_account,
        decision="decision",
        subject="Approve invoice",
    )
    await _add_email(
        db_session,
        email_id="brief-002",
        account_id=seed_account,
        decision="review",
        subject="Looks like a partner reply",
    )

    response = await app_client.get("/api/briefing/today")
    assert response.status_code == 200
    body = response.json()
    decision_ids = {item["id"] for item in body["blocks"]["decisions"]["data"]}
    waiting_ids = {item["id"] for item in body["blocks"]["people_waiting"]["data"]}
    assert "brief-001" in decision_ids
    assert "brief-002" in waiting_ids


@pytest.mark.integration
async def test_briefing_stale_block_lists_old_projectbox_tasks(
    app_client: AsyncClient,
    _stub_projectbox,
) -> None:
    """Project-Box tasks open + untouched for >7 days appear in the stale block.

    Replaces the legacy kanban-table assertion — Project-Box is now the
    canonical task system, so the stale block reads from there.
    """
    from datetime import datetime, timedelta, timezone

    from schemas.projectbox import ProjectBoxTask

    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    stub = _stub_projectbox  # autouse fixture exposes the in-memory store
    stub["ancient.md"] = ProjectBoxTask(
        id="ancient.md",
        title="ancient task",
        status="open",
        dateCreated=long_ago,
        dateModified=long_ago,
        tags=["task"],
    )

    body = (await app_client.get("/api/briefing/today")).json()
    titles = {item["title"] for item in body["blocks"]["stale"]["data"]}
    assert "ancient task" in titles


@pytest.mark.integration
async def test_snoozed_projectbox_task_is_hidden_from_stale_block(
    app_client: AsyncClient,
    _stub_projectbox,
) -> None:
    """Project-Box task snoozes hide stale items by filename."""
    from schemas.projectbox import ProjectBoxTask

    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    _stub_projectbox["snoozed.md"] = ProjectBoxTask(
        id="snoozed.md",
        title="snoozed projectbox task",
        status="open",
        dateCreated=long_ago,
        dateModified=long_ago,
        tags=["task"],
    )
    payload = {
        "item_type": "task",
        "source_id": "snoozed.md",
        "title": "snoozed projectbox task",
        "wake_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    created = await app_client.post("/api/briefing/snoozes", json=payload)
    assert created.status_code == 200

    body = (await app_client.get("/api/briefing/today")).json()
    titles = {item["title"] for item in body["blocks"]["stale"]["data"]}
    assert "snoozed projectbox task" not in titles


@pytest.mark.integration
async def test_briefing_cache_round_trip(
    app_client: AsyncClient, db_session: AsyncSession, seed_account: str
) -> None:
    """Two reads in a row should reuse the Redis-cached payload."""
    await _add_email(
        db_session,
        email_id="brief-cache",
        account_id=seed_account,
        decision="decision",
        subject="Cache hit",
    )
    first = (await app_client.get("/api/briefing/today")).json()
    second = (await app_client.get("/api/briefing/today")).json()
    assert first["cached"] is False
    assert second["cached"] is True


@pytest.mark.integration
async def test_briefing_refresh_busts_cache(
    app_client: AsyncClient, db_session: AsyncSession, seed_account: str
) -> None:
    """``POST /api/briefing/refresh`` returns ``cached=False``."""
    await _add_email(
        db_session,
        email_id="brief-refresh",
        account_id=seed_account,
        decision="decision",
        subject="Forced refresh",
    )
    await app_client.get("/api/briefing/today")
    response = await app_client.post("/api/briefing/refresh")
    assert response.status_code == 200
    assert response.json()["cached"] is False


@pytest.mark.integration
async def test_snooze_wake_sweep_restores_task_visibility(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Past-due snoozes on a task restore ``show_in_briefing=True``."""
    import uuid

    task_id = uuid.uuid4()
    task = Task(
        id=task_id,
        title="snoozed item",
        column_id="today",
        position=0,
        energy="low_stakes",
        show_in_briefing=False,
        stuck_since=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.flush()
    await db_session.commit()

    payload = {
        "item_type": "task",
        "source_id": str(task_id),
        "title": task.title,
        "wake_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
    }
    created = await app_client.post("/api/briefing/snoozes", json=payload)
    assert created.status_code == 200

    swept = await app_client.post("/api/briefing/sweep")
    assert swept.status_code == 200
    assert swept.json()["woken"] >= 1

    await db_session.refresh(task)
    assert task.show_in_briefing is True


def test_snooze_service_pure_helpers() -> None:
    """Sanity: lifespan helpers tolerate a ``None`` task gracefully."""
    import asyncio

    async def go() -> None:
        await snooze_service.stop_in_lifespan(None)

    asyncio.run(go())
