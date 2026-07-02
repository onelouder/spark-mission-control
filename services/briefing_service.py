"""Daily-briefing assembly.

Builds the same block shape v1 exposed at ``/api/briefing/today``:

- ``decisions`` — emails awaiting a decision (partner contacts + review).
- ``people_waiting`` — emails where the user owes a reply, derived from
  triage rows with ``decision=review`` from a partner contact.
- ``runway`` — today's calendar timeline (Decapoda) + in-progress tasks.
- ``stale`` — Project-Box tasks that haven't moved in 7+ days.
- ``snoozed_now_awake`` — :class:`SnoozeItem` rows past their ``wake_at``
  (the snooze sweep will fully process them on the next tick).

Heavy LLM blocks (``threads``, ``pulse``) stay in v1 for now — they
depend on external LLMs that v2 hasn't wired up yet.

The full assembly is cached in Redis for 5 minutes per day-key so
back-to-back requests don't re-query Postgres.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from cache import briefing_cache
from repositories import email_repo, snooze_repo
from schemas.briefing import Briefing, BriefingBlock, BriefingItem
from services import projectbox_client, runway_service
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)

STALE_THRESHOLD = timedelta(days=7)


async def build_briefing(
    session: AsyncSession,
    *,
    for_date: Optional[date] = None,
    use_cache: bool = True,
) -> Briefing:
    """Return a fully-assembled :class:`Briefing` (Redis-cached)."""
    when = for_date or date.today()

    if use_cache:
        cached = await briefing_cache.load(when)
        if cached is not None:
            cached["cached"] = True
            return Briefing.model_validate(cached)

    blocks = {
        "decisions": await _build_decisions_block(session),
        "people_waiting": await _build_people_waiting_block(session),
        "runway": await _build_runway_block(session),
        "stale": await _build_stale_block(session),
        "snoozed_now_awake": await _build_snoozed_block(session),
    }
    payload = Briefing(
        date=when,
        cached=False,
        cached_at=datetime.now(timezone.utc),
        blocks=blocks,
    )
    await briefing_cache.store(when, payload.model_dump())
    return payload


async def invalidate_today() -> int:
    """Convenience wrapper used by mutating endpoints."""
    return await briefing_cache.invalidate(date.today())


async def build_runway(
    session: AsyncSession,
) -> dict[str, Any]:
    """Return the runway payload (also embedded in the full briefing)."""
    snoozed = await snooze_repo.snoozed_source_ids(session, item_type="task")
    return await runway_service.build_runway_block(snoozed_task_ids=snoozed)


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------


async def _build_decisions_block(session: AsyncSession) -> BriefingBlock:
    rows = await email_repo.list_for_briefing(
        session, decisions=("decision",), limit=20
    )
    items = [
        BriefingItem(
            id=row.id,
            type="email",
            title=row.subject or "(no subject)",
            context=row.from_address,
            detail=row.from_name,
            source="email",
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return BriefingBlock(name="decisions", count=len(items), data=items)


async def _build_people_waiting_block(session: AsyncSession) -> BriefingBlock:
    rows = await email_repo.list_for_briefing(
        session, decisions=("review",), limit=20
    )
    items = [
        BriefingItem(
            id=row.id,
            type="email",
            title=row.subject or "(no subject)",
            context=row.from_address,
            detail="Awaiting human review",
            source="email",
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return BriefingBlock(name="people_waiting", count=len(items), data=items)


async def _build_runway_block(session: AsyncSession) -> BriefingBlock:
    payload = await build_runway(session)
    count = len(payload.get("timeline_items", [])) + len(
        payload.get("today_tasks", [])
    )
    return BriefingBlock(name="runway", count=count, data=[], extra=payload)


async def _build_stale_block(session: AsyncSession) -> BriefingBlock:
    """Project-Box tasks open + untouched > :data:`STALE_THRESHOLD`.

    Replaces the legacy ``kanban.tasks`` query — Project-Box is now the
    source of truth for tasks. If Project-Box is unreachable, the block
    is returned empty (logged at WARNING) so the rest of the briefing
    still assembles.
    """
    cutoff = datetime.now(timezone.utc) - STALE_THRESHOLD
    snoozed_task_ids = await snooze_repo.snoozed_source_ids(
        session, item_type="task"
    )
    try:
        tasks = await projectbox_client.list_tasks()
    except ProjectBoxOffline as exc:
        logger.warning(
            "briefing_service: Project-Box offline (%s); stale block empty", exc
        )
        return BriefingBlock(name="stale", count=0, data=[])

    truly_stale = []
    for task in tasks:
        if task.id in snoozed_task_ids:
            continue
        if task.status not in {"open", "in-progress"}:
            continue
        modified = task.dateModified
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        if modified <= cutoff:
            truly_stale.append(task)
    truly_stale.sort(key=lambda t: t.dateModified)
    truly_stale = truly_stale[:20]

    items = [
        BriefingItem(
            id=task.id,
            type="task",
            title=task.title,
            context=", ".join(task.projects) or task.status,
            detail=(
                f"open since {task.dateModified.date().isoformat()}"
                if not task.completedDate
                else None
            ),
            source="projectbox",
            updated_at=task.dateModified,
        )
        for task in truly_stale
    ]
    return BriefingBlock(name="stale", count=len(items), data=items)


async def _build_snoozed_block(session: AsyncSession) -> BriefingBlock:
    rows = await snooze_repo.list_snoozed(session, only_awake=True)
    items = [
        BriefingItem(
            id=str(row.id),
            type=row.item_type,
            title=row.title or row.source_id,
            context=row.context,
            detail=f"snoozed since {row.created_at.isoformat()}" if row.created_at else None,
            source="snooze",
            updated_at=row.wake_at,
        )
        for row in rows
    ]
    return BriefingBlock(name="snoozed_now_awake", count=len(items), data=items)
