"""Decapoda-backed runway block tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from schemas.projectbox import ProjectBoxTask
from services import decapoda_client, runway_service


@pytest.fixture
def mock_calendar(monkeypatch):
    async def _fetch(*, days: int = 2, limit: int = 50):
        return [
            {
                "id": "evt-1",
                "title": "Standup",
                "start": "2026-05-28T16:00:00Z",
                "end": "2026-05-28T16:30:00Z",
                "attendees": [
                    {
                        "name": "Alex",
                        "address": "alex@example.com",
                        "type": "required",
                    }
                ],
                "location": "Teams",
                "webLink": "https://example.com/meet",
            },
            {
                "id": "evt-cancelled",
                "title": "Canceled: Old sync",
                "start": "2026-05-28T17:00:00Z",
                "end": "2026-05-28T17:30:00Z",
                "attendees": [],
            },
        ]

    monkeypatch.setattr(decapoda_client, "fetch_calendar_events", _fetch)


@pytest.mark.integration
async def test_runway_lists_in_progress_tasks(
    app_client: AsyncClient,
    _stub_projectbox,
    mock_calendar,
    monkeypatch,
) -> None:
    """In-progress Project-Box tasks appear in ``today_tasks``."""
    import pytz

    pt = pytz.timezone("America/Los_Angeles")
    fixed = pt.localize(datetime(2026, 5, 28, 9, 0, 0))

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.astimezone(timezone.utc).replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr(runway_service, "datetime", _FixedDateTime)

    now = datetime.now(timezone.utc)
    _stub_projectbox["active.md"] = ProjectBoxTask(
        id="active.md",
        title="Ship runway",
        status="in-progress",
        dateCreated=now,
        dateModified=now,
        tags=["task"],
    )

    response = await app_client.get("/api/briefing/runway")
    assert response.status_code == 200
    body = response.json()
    titles = {row["title"] for row in body["today_tasks"]}
    assert "Ship runway" in titles
    assert body["current_time"] == "09:00"


@pytest.mark.integration
async def test_full_briefing_includes_runway_block(
    app_client: AsyncClient,
    mock_calendar,
) -> None:
    body = (await app_client.get("/api/briefing/today")).json()
    assert "runway" in body["blocks"]
    assert body["blocks"]["runway"]["extra"] is not None
    assert "timeline_items" in body["blocks"]["runway"]["extra"]
