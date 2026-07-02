"""Pydantic DTOs for the email-triage surface.

``EmailTriage`` rows are *metadata-only* (no raw email bodies). The shape
mirrors v1 ``processed_emails.json`` entries the briefing actually
consumes so the existing UI can read them without rewrites.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class EmailTriageRead(BaseModel):
    """Single email-triage row as returned by the API."""

    id: str
    account_id: str
    context_id: Optional[str] = None
    subject: Optional[str] = None
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    received_at: Optional[datetime] = None
    contact_tier: Optional[str] = None
    final_decision: str
    filter_reason: Optional[str] = None
    briefing_handled: bool = False
    converted_to_task: bool = False
    converted_task_id: Optional[uuid.UUID] = None
    analysis: dict[str, Any] = Field(default_factory=dict)
    pipeline_stages: dict[str, Any] = Field(default_factory=dict)
    processed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EmailDecision(BaseModel):
    """Update the triage decision for an email."""

    final_decision: str = Field(..., min_length=1, max_length=16)
    filter_reason: Optional[str] = None
    briefing_handled: Optional[bool] = None


class EmailToTaskRequest(BaseModel):
    """Convert an email into a Project-Box task."""

    title: Optional[str] = None
    column: Optional[str] = "today"
    notes: Optional[str] = None


class EmailTriageList(BaseModel):
    """Paginated triage listing."""

    items: list[EmailTriageRead]
    total: int


class ContactRead(BaseModel):
    """Contact entry as returned by the API."""

    id: uuid.UUID
    email: str
    display_name: Optional[str] = None
    domain: Optional[str] = None
    tier: str = "unknown"
    interaction_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ContactTierWrite(BaseModel):
    """Set / clear a contact tier."""

    tier: str = Field(..., min_length=1, max_length=32)
