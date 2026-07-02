"""Briefing HTTP routes."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from schemas.briefing import Briefing, SnoozeRead, SnoozeRequest
from services import briefing_service, snooze_service

router = APIRouter(tags=["briefing"])


@router.get("/api/briefing/runway")
async def get_runway(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Today's calendar timeline + in-progress Project-Box tasks."""
    return await briefing_service.build_runway(session)


@router.get("/api/briefing/today", response_model=Briefing)
async def get_today(
    no_cache: bool = Query(False, description="Bypass Redis cache"),
    for_date: Optional[date] = Query(None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> Briefing:
    """Return today's briefing (or a specific date if ``?date=...``)."""
    return await briefing_service.build_briefing(
        session, for_date=for_date, use_cache=not no_cache
    )


@router.post("/api/briefing/refresh", response_model=Briefing)
async def refresh_today(
    session: AsyncSession = Depends(get_session),
) -> Briefing:
    """Force-refresh today's briefing (and re-populate the cache)."""
    return await briefing_service.build_briefing(session, use_cache=False)


@router.post("/api/briefing/snoozes", response_model=SnoozeRead)
async def create_snooze(
    payload: SnoozeRequest,
    session: AsyncSession = Depends(get_session),
) -> SnoozeRead:
    """Snooze a briefing item until ``wake_at``."""
    row = await snooze_service.create_snooze(
        session,
        item_type=payload.item_type,
        source_id=payload.source_id,
        wake_at=payload.wake_at,
        title=payload.title,
        context=payload.context,
        original_block=payload.original_block,
    )
    return SnoozeRead.model_validate(row)


@router.get("/api/briefing/snoozes", response_model=list[SnoozeRead])
async def list_snoozes(
    session: AsyncSession = Depends(get_session),
) -> list[SnoozeRead]:
    """List every active snooze."""
    rows = await snooze_service.list_snoozes(session)
    return [SnoozeRead.model_validate(r) for r in rows]


@router.delete("/api/briefing/snoozes/{snooze_id}")
async def delete_snooze(
    snooze_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Un-snooze (delete the row, restore visibility)."""
    deleted = await snooze_service.remove_snooze(session, snooze_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Snooze not found")
    return {"deleted": True}


@router.post("/api/briefing/sweep")
async def sweep_now(
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Manually trigger the wake-up sweep (useful for testing / cron)."""
    woken = await snooze_service.sweep_once(session)
    return {"woken": woken}
