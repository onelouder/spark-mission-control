"""Decapoda-Lite HTTP client (calendar + future integrations)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


async def fetch_calendar_events(*, days: int = 2, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch calendar events from Decapoda for the runway timeline.

    Filters mirror v1 ``briefing.get_calendar_events``:

    - skip cancelled events and titles prefixed with ``Canceled:``
    - skip all-day events (``T00:00:00`` start)
    """
    settings = get_settings()
    base = settings.decapoda_base_url.rstrip("/")
    url = f"{base}/v1/calendar/today?days={days}&limit={limit}"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("decapoda_client: calendar fetch failed (%s)", exc)
        return []

    events: list[dict[str, Any]] = []
    for event in data.get("value", []):
        if event.get("isCancelled", False):
            continue

        subject = event.get("subject", "")
        lowered = subject.lower()
        if lowered.startswith("canceled:") or lowered.startswith("cancelled:"):
            continue

        start = event.get("start", "")
        if "T00:00:00" in start:
            continue

        events.append(
            {
                "id": event.get("id"),
                "title": subject,
                "start": start,
                "end": event.get("end"),
                "attendees": event.get("attendees", []),
                "location": event.get("location"),
                "webLink": event.get("webLink"),
            }
        )
    return events
