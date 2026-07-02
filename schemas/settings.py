"""Pydantic DTOs for accounts, contexts, and accomplishments (Sprint 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


class AccountRead(BaseModel):
    """Mail/calendar account row."""

    id: str
    name: str
    email: str
    provider: str
    icon: Optional[str] = None
    color: Optional[str] = None
    gateway_url: Optional[str] = None
    tokens_path: Optional[str] = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AccountCreate(BaseModel):
    """Create-payload for ``POST /api/accounts``."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str
    email: str
    provider: str
    icon: Optional[str] = None
    color: Optional[str] = None
    gateway_url: Optional[str] = None
    tokens_path: Optional[str] = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class AccountUpdate(BaseModel):
    """Patch-payload for ``PATCH /api/accounts/{id}``."""

    name: Optional[str] = None
    email: Optional[str] = None
    provider: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    gateway_url: Optional[str] = None
    tokens_path: Optional[str] = None
    enabled: Optional[bool] = None
    settings: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class ContextRead(BaseModel):
    """Life-domain context row."""

    id: str
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    provider: Optional[str] = None
    user_email: Optional[str] = None
    enabled: bool = True
    match_rules: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ContextCreate(BaseModel):
    """Create-payload for ``POST /api/contexts``."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    provider: Optional[str] = None
    user_email: Optional[str] = None
    enabled: bool = True
    match_rules: dict[str, Any] = Field(default_factory=dict)


class ContextUpdate(BaseModel):
    """Patch-payload for ``PATCH /api/contexts/{id}``."""

    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    provider: Optional[str] = None
    user_email: Optional[str] = None
    enabled: Optional[bool] = None
    match_rules: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Accomplishments
# ---------------------------------------------------------------------------


class AccomplishmentRead(BaseModel):
    """Single accomplishment row."""

    id: uuid.UUID
    text: str
    source: str = "manual"
    recorded_at: datetime

    model_config = {"from_attributes": True}


class AccomplishmentCreate(BaseModel):
    """Create-payload for ``POST /api/accomplishments``."""

    text: str = Field(..., min_length=1)
    source: str = "manual"
