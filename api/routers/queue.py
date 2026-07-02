"""Agent queue + dispatch HTTP routes.

Endpoints (v1-compatible):

- ``GET    /api/queue``                        — items + by_column + stats
- ``POST   /api/queue``                        — create item
- ``GET    /api/queue/{id}``                   — fetch one
- ``PATCH  /api/queue/{id}``                   — partial update
- ``DELETE /api/queue/{id}``                   — delete
- ``POST   /api/queue/{id}/dispatch``          — dispatch to a named agent
- ``POST   /api/queue/{id}/dispatch/auto``     — auto-route then dispatch
- ``GET    /api/queue/{id}/status``            — latest dispatch state

The router takes care of HTTP-layer concerns only; all business rules live
in :mod:`services.queue_service` / :mod:`services.dispatch_service`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from repositories import dispatch_repo
from schemas.queue import (
    DispatchRequest,
    DispatchStatus,
    QueueItemCreate,
    QueueItemRead,
    QueueItemUpdate,
    QueueOverview,
)
from services import dispatch_service, openclaw_client, queue_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["queue"])


@router.get("/api/queue", response_model=QueueOverview)
async def get_queue(
    session: AsyncSession = Depends(get_session),
) -> QueueOverview:
    """Return the full queue snapshot (items, by-column, stats)."""
    return await queue_service.overview(session)


@router.post("/api/queue", response_model=QueueItemRead)
async def create_queue_item(
    item: QueueItemCreate,
    session: AsyncSession = Depends(get_session),
) -> QueueItemRead:
    """Create a new queue item."""
    return await queue_service.create(session, item)


@router.get("/api/queue/agents", response_model=list[dict[str, str]])
async def list_known_agents() -> list[dict[str, str]]:
    """Return the agents this Mission Control instance can dispatch to."""
    return [
        {"id": agent_id, **info}
        for agent_id, info in openclaw_client.AGENT_REGISTRY.items()
    ]


@router.get("/api/queue/{item_id}", response_model=QueueItemRead)
async def get_queue_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> QueueItemRead:
    """Fetch one queue item."""
    item = await queue_service.get(session, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.patch("/api/queue/{item_id}", response_model=QueueItemRead)
async def update_queue_item(
    item_id: str,
    updates: QueueItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> QueueItemRead:
    """Apply a partial update to a queue item."""
    item = await queue_service.update(session, item_id, updates)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.delete("/api/queue/{item_id}")
async def delete_queue_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete a queue item."""
    deleted = await queue_service.remove(session, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "deleted", "id": item_id}


@router.post("/api/queue/{item_id}/dispatch")
async def dispatch_queue_item(
    item_id: str,
    request: DispatchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Dispatch a queue item to a specific agent via OpenClaw."""
    outcome = await dispatch_service.dispatch(
        session,
        queue_item_id=item_id,
        agent_id=request.agent_id,
        custom_prompt=request.custom_prompt,
    )
    if outcome is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if not outcome.success:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": outcome.error or "Dispatch failed",
                "offline": outcome.offline,
                "agent_id": request.agent_id,
                "job_id": outcome.job.id,
            },
        )
    return {
        "success": True,
        "run_id": outcome.run_id,
        "offline": outcome.offline,
        "agent_id": request.agent_id,
        "job_id": outcome.job.id,
    }


@router.post("/api/queue/{item_id}/dispatch/auto")
async def dispatch_queue_item_auto(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Auto-route then dispatch a queue item."""
    item = await queue_service.get(session, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    agent_id = queue_service.suggest_agent_for_item(item)
    outcome = await dispatch_service.dispatch(
        session,
        queue_item_id=item_id,
        agent_id=agent_id,
        custom_prompt=None,
    )
    if outcome is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if not outcome.success:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": outcome.error or "Dispatch failed",
                "offline": outcome.offline,
                "agent_id": agent_id,
                "job_id": outcome.job.id,
            },
        )
    return {
        "success": True,
        "run_id": outcome.run_id,
        "offline": outcome.offline,
        "agent_id": agent_id,
        "job_id": outcome.job.id,
    }


@router.get("/api/queue/{item_id}/status", response_model=list[DispatchStatus])
async def queue_item_status(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[DispatchStatus]:
    """Return the dispatch job history for a queue item (newest first)."""
    jobs = await dispatch_repo.list_for_queue_item(session, item_id)
    return [DispatchStatus.model_validate(j) for j in jobs]
