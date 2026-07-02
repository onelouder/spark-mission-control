"""OpenClaw constellation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from services import constellation_service

router = APIRouter(tags=["constellation"])


@router.get("/api/openclaw/constellation")
async def get_constellation(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return OpenClaw gateway, agent, queue, and config state."""
    return await constellation_service.overview(session)


@router.get("/api/constellation")
async def get_constellation_alias(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Short alias for the OpenClaw constellation overview."""
    return await constellation_service.overview(session)
