"""Tests for the focus session API (Project-Box + Redis)."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_focus_lifecycle(
    app_client: AsyncClient, _stub_projectbox
) -> None:
    """A focus session can be started, queried, and stopped on a Project-Box task."""
    task = (
        await app_client.post("/api/tasks", json={"title": "deep work"})
    ).json()
    task_id = task["id"]
    assert task_id.endswith(".md")

    started_at = datetime.now(timezone.utc).isoformat()
    start = await app_client.post(
        "/api/focus/start",
        json={
            "task_id": task_id,
            "started_at": started_at,
            "mode": "pomodoro",
        },
    )
    assert start.status_code == 200
    assert start.json()["task_id"] == task_id
    assert start.json()["mode"] == "pomodoro"
    assert start.json()["source"] == "projectbox"

    status = await app_client.get("/api/focus/status")
    assert status.status_code == 200
    payload = status.json()["session"]
    assert payload is not None
    assert payload["task_id"] == task_id
    assert payload["task_title"] == "deep work"
    assert "elapsed_seconds" in payload
    assert "remaining_seconds" in payload

    stop = await app_client.post("/api/focus/stop")
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True
    assert stop.json()["time_logged"] is True

    cleared = await app_client.get("/api/focus/status")
    assert cleared.json() == {"session": None}


@pytest.mark.integration
async def test_focus_start_rejects_unknown_task(app_client: AsyncClient) -> None:
    """Starting focus on a non-existent task returns 404."""
    response = await app_client.post(
        "/api/focus/start",
        json={
            "task_id": "no-such-task.md",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "mode": "pomodoro",
        },
    )
    assert response.status_code == 404
