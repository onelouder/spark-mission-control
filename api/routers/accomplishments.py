"""HTTP routes for logged accomplishments (Sprint 4)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.kanban import Accomplishment
from db.session import get_session
from schemas.settings import AccomplishmentCreate, AccomplishmentRead

router = APIRouter(tags=["accomplishments"])


@router.get("/api/accomplishments", response_model=list[AccomplishmentRead])
async def list_accomplishments(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[AccomplishmentRead]:
    """Most recent accomplishments first."""
    stmt = (
        select(Accomplishment)
        .order_by(desc(Accomplishment.recorded_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [AccomplishmentRead.model_validate(r) for r in rows]


@router.post(
    "/api/accomplishments", response_model=AccomplishmentRead, status_code=201
)
async def create_accomplishment(
    payload: AccomplishmentCreate,
    session: AsyncSession = Depends(get_session),
) -> AccomplishmentRead:
    """Log a new accomplishment row."""
    row = Accomplishment(
        id=uuid.uuid4(),
        text=payload.text,
        source=payload.source,
        recorded_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return AccomplishmentRead.model_validate(row)


@router.delete("/api/accomplishments/{accomplishment_id}")
async def delete_accomplishment(
    accomplishment_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove an accomplishment row."""
    row = await session.get(Accomplishment, accomplishment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Accomplishment not found")
    await session.delete(row)
    await session.flush()
    return {"deleted": True, "id": str(accomplishment_id)}
