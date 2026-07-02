"""Today's Runway block — calendar timeline + in-progress tasks."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

import pytz

from config import get_settings
from schemas.projectbox import ProjectBoxTask
from services import decapoda_client, projectbox_client
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)

PT = pytz.timezone("America/Los_Angeles")

_ROOM_PATTERNS = {
    "room",
    "conf",
    "board",
    "lobby",
    "lounge",
    "auditorium",
    "kitchen",
    "lab",
}


def _is_real_person(att: dict[str, Any]) -> bool:
    """Return ``True`` when an attendee looks like a person, not a room."""
    settings = get_settings()
    addr = att.get("address", "").lower()
    if not addr or addr == settings.auth_self_email.lower():
        return False
    if att.get("type", "").lower() == "resource":
        return False
    local = addr.split("@")[0]
    name = att.get("name", "").lower()
    if any(p in local for p in _ROOM_PATTERNS) or any(
        p in name for p in _ROOM_PATTERNS
    ):
        return False
    if name == addr:
        return False
    return True


async def build_runway_block(
    *,
    snoozed_task_ids: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Build the runway payload returned by ``GET /api/briefing/runway``.

    Args:
        snoozed_task_ids: Task source IDs hidden by active snoozes.

    Returns:
        Dict with ``timeline_items``, ``today_tasks``, ``work_windows``,
        and ``current_time`` (Pacific HH:MM).
    """
    snoozed = set(snoozed_task_ids or [])
    today = datetime.now(PT).date()
    calendar_events = await decapoda_client.fetch_calendar_events()

    today_tasks: list[dict[str, Any]] = []
    try:
        tasks = await projectbox_client.list_tasks()
    except ProjectBoxOffline as exc:
        logger.warning("runway_service: Project-Box offline (%s)", exc)
        tasks = []

    for task in tasks:
        if task.id in snoozed:
            continue
        if task.status == "in-progress":
            today_tasks.append(_task_row(task))

    timeline_items: list[dict[str, Any]] = []
    for event in calendar_events:
        item = _event_timeline_row(event, today=today)
        if item is not None:
            timeline_items.append(item)

    timeline_items.sort(
        key=lambda row: (row.get("date", ""), row.get("time", "00:00"))
    )

    return {
        "timeline_items": timeline_items,
        "today_tasks": today_tasks,
        "work_windows": [],
        "current_time": datetime.now(PT).strftime("%H:%M"),
    }


def _task_row(task: ProjectBoxTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "type": "task",
        "title": task.title,
        "time": None,
        "energy": "low_stakes",
    }


def _event_timeline_row(
    event: dict[str, Any], *, today: date
) -> Optional[dict[str, Any]]:
    raw_start = event["start"].replace("Z", "+00:00")
    start_time = datetime.fromisoformat(raw_start)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    start_pt = start_time.astimezone(PT)
    event_date = start_pt.date()
    if event_date != today:
        return None

    attendees = event.get("attendees", [])
    other_attendees = [att for att in attendees if _is_real_person(att)]
    attendee_names = [
        att.get("name", "Unknown") for att in other_attendees if att.get("name")
    ]

    raw_end = event.get("end", event["start"]).replace("Z", "+00:00")
    end_time = datetime.fromisoformat(raw_end)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    end_pt = end_time.astimezone(PT)

    duration_mins = int((end_pt - start_pt).total_seconds() / 60)
    if duration_mins <= 0 or duration_mins > 480:
        duration_mins = 60

    return {
        "type": "meeting",
        "day": "Today",
        "date": event_date.isoformat(),
        "time": start_pt.strftime("%H:%M"),
        "end_time": end_pt.strftime("%H:%M"),
        "duration_mins": duration_mins,
        "title": event["title"],
        "attendees_count": len(other_attendees),
        "attendee_names": attendee_names,
        "location": event.get("location", ""),
        "webLink": event.get("webLink", ""),
    }
