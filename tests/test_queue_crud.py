"""End-to-end CRUD tests for ``/api/queue`` (Sprint 2)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_create_lists_then_stats(app_client: AsyncClient) -> None:
    """Create two items and confirm overview returns counts."""
    a = await app_client.post(
        "/api/queue",
        json={"title": "Investigate flaky deploy", "complexity": "deep", "tags": ["devops"]},
    )
    b = await app_client.post(
        "/api/queue",
        json={"title": "Update README badge", "complexity": "quick"},
    )
    assert a.status_code == 200
    assert b.status_code == 200

    overview = (await app_client.get("/api/queue")).json()
    assert overview["stats"]["total"] >= 2
    titles = {item["title"] for item in overview["items"]}
    assert {"Investigate flaky deploy", "Update README badge"} <= titles
    # quick beats deep in priority (5 vs -5)
    quick = next(i for i in overview["items"] if i["title"] == "Update README badge")
    deep = next(i for i in overview["items"] if i["title"] == "Investigate flaky deploy")
    assert quick["priority"] > deep["priority"]


@pytest.mark.integration
async def test_patch_to_review_stamps_completed_at(app_client: AsyncClient) -> None:
    """PATCH column='review' should populate ``completed_at``."""
    created = (
        await app_client.post("/api/queue", json={"title": "ship sprint 2"})
    ).json()
    patched = await app_client.patch(
        f"/api/queue/{created['id']}", json={"column": "review"}
    )
    assert patched.status_code == 200
    assert patched.json()["column"] == "review"
    assert patched.json()["completed_at"]


@pytest.mark.integration
async def test_delete_then_404(app_client: AsyncClient) -> None:
    """Delete removes the item; subsequent fetch returns 404."""
    created = (
        await app_client.post("/api/queue", json={"title": "doomed item"})
    ).json()
    deleted = await app_client.delete(f"/api/queue/{created['id']}")
    assert deleted.status_code == 200

    missing = await app_client.get(f"/api/queue/{created['id']}")
    assert missing.status_code == 404


@pytest.mark.integration
async def test_known_agents_endpoint(app_client: AsyncClient) -> None:
    """``/api/queue/agents`` returns the in-process registry."""
    response = await app_client.get("/api/queue/agents")
    assert response.status_code == 200
    agents = response.json()
    ids = {a["id"] for a in agents}
    assert {"jarvis", "aria", "peter"} <= ids


@pytest.mark.integration
async def test_create_with_project_autocreates_stub(app_client: AsyncClient) -> None:
    """Specifying a project id on creation upserts a project stub."""
    created = await app_client.post(
        "/api/queue",
        json={"title": "Venture growth plan", "project": "venture-bd"},
    )
    assert created.status_code == 200
    assert created.json()["project"] == "venture-bd"
