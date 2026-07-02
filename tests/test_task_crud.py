"""Task API tests — Project-Box is the canonical backend."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_create_then_list_task(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """POST /api/tasks creates a Project-Box task visible on GET."""
    created = await app_client.post(
        "/api/tasks", json={"title": "Write tests", "column": "today"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Write tests"
    assert body["source"] == "projectbox"
    assert body["id"].endswith(".md")
    task_id = body["id"]

    listed = await app_client.get("/api/tasks")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["source"] == "projectbox"
    ids = [t["id"] for t in payload["tasks"]]
    assert task_id in ids


@pytest.mark.integration
async def test_update_projectbox_status_via_put(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """PUT with a column maps to Project-Box status."""
    created = (
        await app_client.post("/api/tasks", json={"title": "movable"})
    ).json()

    moved = await app_client.put(
        f"/api/tasks/{created['id']}",
        json={"column": "done"},
    )
    assert moved.status_code == 200
    assert moved.json()["status"] == "done"


@pytest.mark.integration
async def test_delete_archives_projectbox_task(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """DELETE archives the Project-Box task (removed from active list)."""
    created = (
        await app_client.post("/api/tasks", json={"title": "doomed"})
    ).json()

    deleted = await app_client.delete(f"/api/tasks/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json().get("success") is True

    listed = (await app_client.get("/api/tasks")).json()["tasks"]
    assert created["id"] not in [t["id"] for t in listed]


@pytest.mark.integration
async def test_delete_unknown_legacy_uuid_returns_404(
    app_client: AsyncClient,
) -> None:
    """DELETE on a non-existent legacy UUID returns 404."""
    response = await app_client.delete(
        "/api/tasks/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_to_kanban_deprecated(app_client: AsyncClient) -> None:
    """Legacy /to-kanban returns 410 Gone."""
    response = await app_client.post("/api/tasks/anything.md/to-kanban")
    assert response.status_code == 410


@pytest.mark.integration
async def test_snooze_rejects_projectbox_id(app_client: AsyncClient) -> None:
    """Snooze on Project-Box tasks points callers at briefing snoozes."""
    response = await app_client.post(
        "/api/tasks/example.md/snooze", json={"hours": 2}
    )
    assert response.status_code == 400
