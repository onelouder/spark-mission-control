"""Integration tests for the Project-Box surface.

Uses the autouse ``_stub_projectbox`` fixture from conftest so no live
Project-Box is required. Each test gets a fresh in-memory store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from schemas.projectbox import ProjectBoxTask
from services import projectbox_client
from services.projectbox_client import ProjectBoxOffline


@pytest.mark.integration
async def test_projectbox_health(app_client: AsyncClient) -> None:
    """``/api/projectbox/health`` returns the stub's status."""
    response = await app_client.get("/api/projectbox/health")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["reachable"] is True


@pytest.mark.integration
async def test_projectbox_proxy_round_trip(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """Create → list → get → archive against the proxied surface."""
    created = await app_client.post(
        "/api/projectbox/tasks", json={"title": "Investigate flaky deploy"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Investigate flaky deploy"
    filename = body["id"]
    assert filename in _stub_projectbox

    listed = await app_client.get("/api/projectbox/tasks")
    assert listed.status_code == 200
    titles = {row["title"] for row in listed.json()}
    assert "Investigate flaky deploy" in titles

    single = await app_client.get(f"/api/projectbox/tasks/{filename}")
    assert single.status_code == 200

    archived = await app_client.delete(f"/api/projectbox/tasks/{filename}")
    assert archived.status_code == 200
    assert filename not in _stub_projectbox


@pytest.mark.integration
async def test_email_to_task_creates_projectbox_task(
    app_client: AsyncClient, db_session, _stub_projectbox
) -> None:
    """Converting an email lands a Project-Box task, not a kanban row."""
    from db.orm.core import Account, EmailTriage

    db_session.add(
        Account(
            id="ops",
            name="Ops Inbox",
            email="ops@example.com",
            provider="gmail",
        )
    )
    db_session.add(
        EmailTriage(
            id="pb-email-1",
            account_id="ops",
            subject="Vendor renewal due Friday",
            from_address="vendor@example.com",
            from_name="Vendor",
            received_at=datetime.now(timezone.utc),
            final_decision="review",
            briefing_handled=False,
            converted_to_task=False,
            analysis={},
            pipeline_stages={},
        )
    )
    await db_session.flush()
    await db_session.commit()

    response = await app_client.post(
        "/api/emails/pb-email-1/to-task", json={}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["already_converted"] is False
    assert body["offline"] is False
    assert body["task_id"].endswith(".md")
    assert body["task_id"] in _stub_projectbox

    # Idempotent re-call returns the same filename.
    second = await app_client.post(
        "/api/emails/pb-email-1/to-task", json={}
    )
    assert second.status_code == 200
    assert second.json()["already_converted"] is True
    assert second.json()["task_id"] == body["task_id"]


@pytest.mark.integration
async def test_email_to_task_handles_offline(
    app_client: AsyncClient, db_session, monkeypatch
) -> None:
    """When Project-Box is offline, the email stays unconverted."""
    from db.orm.core import Account, EmailTriage

    async def _offline(*_args, **_kwargs):
        raise ProjectBoxOffline("simulated outage")

    monkeypatch.setattr(projectbox_client, "create_task", _offline)

    db_session.add(
        Account(
            id="ops2",
            name="Ops",
            email="ops2@example.com",
            provider="gmail",
        )
    )
    db_session.add(
        EmailTriage(
            id="pb-email-offline",
            account_id="ops2",
            subject="Reschedule meeting",
            from_address="x@y.com",
            received_at=datetime.now(timezone.utc),
            final_decision="review",
            briefing_handled=False,
            converted_to_task=False,
            analysis={},
            pipeline_stages={},
        )
    )
    await db_session.flush()
    await db_session.commit()

    response = await app_client.post(
        "/api/emails/pb-email-offline/to-task", json={}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["offline"] is True
    assert body["task_id"] is None

    after = (await app_client.get("/api/emails/pb-email-offline")).json()
    assert after["converted_to_task"] is False


@pytest.mark.integration
async def test_briefing_stale_uses_projectbox(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """The stale block lists Project-Box tasks open >7 days; recent ones excluded."""
    from cache import briefing_cache

    long_ago = datetime.now(timezone.utc) - timedelta(days=14)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    _stub_projectbox["stale.md"] = ProjectBoxTask(
        id="stale.md",
        title="ancient unfinished",
        status="open",
        dateCreated=long_ago,
        dateModified=long_ago,
        tags=["task"],
    )
    _stub_projectbox["fresh.md"] = ProjectBoxTask(
        id="fresh.md",
        title="touched yesterday",
        status="open",
        dateCreated=recent,
        dateModified=recent,
        tags=["task"],
    )
    _stub_projectbox["done.md"] = ProjectBoxTask(
        id="done.md",
        title="already finished",
        status="done",
        dateCreated=long_ago,
        dateModified=long_ago,
        tags=["task"],
    )

    await briefing_cache.invalidate()
    body = (await app_client.get("/api/briefing/today")).json()
    titles = {item["title"] for item in body["blocks"]["stale"]["data"]}
    assert "ancient unfinished" in titles
    assert "touched yesterday" not in titles
    assert "already finished" not in titles
