"""Pydantic DTOs for the daily briefing.

The briefing is a structured response containing one block per content
type (decisions, people-waiting, stale, snoozed-now-awake). Each block
exposes a ``count`` field so the UI can show a badge before the heavy
``data`` list is rendered.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BriefingItem(BaseModel):
    """One row inside a briefing block."""

    id: str
    type: str
    title: str
    context: Optional[str] = None
    detail: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[datetime] = None


class BriefingBlock(BaseModel):
    """A named bundle of related briefing items."""

    name: str
    count: int = 0
    data: list[BriefingItem] = Field(default_factory=list)
    extra: Optional[dict[str, Any]] = None


class Briefing(BaseModel):
    """Top-level briefing payload returned by ``GET /api/briefing/today``."""

    date: date_type
    cached: bool = False
    cached_at: Optional[datetime] = None
    blocks: dict[str, BriefingBlock] = Field(default_factory=dict)


class SnoozeRequest(BaseModel):
    """Create a snooze entry inside ``core.snooze_items``."""

    item_type: str = Field(..., min_length=1, max_length=32)
    source_id: str
    title: Optional[str] = None
    context: Optional[str] = None
    original_block: Optional[str] = None
    wake_at: datetime


class SnoozeRead(BaseModel):
    """A snooze row."""

    id: uuid.UUID
    item_type: str
    source_id: str
    title: Optional[str] = None
    context: Optional[str] = None
    original_block: Optional[str] = None
    wake_at: datetime
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
