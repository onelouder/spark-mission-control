"""HTTP routes for accounts, contexts, and their many-to-many link."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from repositories import settings_repo
from schemas.settings import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ContextCreate,
    ContextRead,
    ContextUpdate,
)

router = APIRouter(tags=["settings"])


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@router.get("/api/accounts", response_model=list[AccountRead])
async def list_accounts(
    session: AsyncSession = Depends(get_session),
) -> list[AccountRead]:
    """List every configured account."""
    rows = await settings_repo.list_accounts(session)
    return [AccountRead.model_validate(row) for row in rows]


@router.post("/api/accounts", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    """Create a new account row."""
    row = await settings_repo.create_account(
        session, data=payload.model_dump()
    )
    return AccountRead.model_validate(row)


@router.get("/api/accounts/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: str,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    """Fetch one account."""
    row = await settings_repo.get_account(session, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.model_validate(row)


@router.patch("/api/accounts/{account_id}", response_model=AccountRead)
async def patch_account(
    account_id: str,
    payload: AccountUpdate,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    """Partial-update an account."""
    row = await settings_repo.update_account(
        session, account_id, changes=payload.model_dump(exclude_unset=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountRead.model_validate(row)


@router.delete("/api/accounts/{account_id}")
async def delete_account(
    account_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove an account."""
    deleted = await settings_repo.delete_account(session, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True, "id": account_id}


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------


@router.get("/api/contexts", response_model=list[ContextRead])
async def list_contexts(
    session: AsyncSession = Depends(get_session),
) -> list[ContextRead]:
    """List every configured context."""
    rows = await settings_repo.list_contexts(session)
    return [ContextRead.model_validate(row) for row in rows]


@router.post("/api/contexts", response_model=ContextRead, status_code=201)
async def create_context(
    payload: ContextCreate,
    session: AsyncSession = Depends(get_session),
) -> ContextRead:
    """Create a new context row."""
    row = await settings_repo.create_context(
        session, data=payload.model_dump()
    )
    return ContextRead.model_validate(row)


@router.get("/api/contexts/{context_id}", response_model=ContextRead)
async def get_context(
    context_id: str,
    session: AsyncSession = Depends(get_session),
) -> ContextRead:
    """Fetch one context."""
    row = await settings_repo.get_context(session, context_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Context not found")
    return ContextRead.model_validate(row)


@router.patch("/api/contexts/{context_id}", response_model=ContextRead)
async def patch_context(
    context_id: str,
    payload: ContextUpdate,
    session: AsyncSession = Depends(get_session),
) -> ContextRead:
    """Partial-update a context."""
    row = await settings_repo.update_context(
        session, context_id, changes=payload.model_dump(exclude_unset=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Context not found")
    return ContextRead.model_validate(row)


@router.delete("/api/contexts/{context_id}")
async def delete_context(
    context_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove a context."""
    deleted = await settings_repo.delete_context(session, context_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Context not found")
    return {"deleted": True, "id": context_id}


# ---------------------------------------------------------------------------
# Account ↔ Context links
# ---------------------------------------------------------------------------


@router.get("/api/accounts/{account_id}/contexts", response_model=list[str])
async def list_account_contexts(
    account_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Return context ids linked to ``account_id``."""
    if await settings_repo.get_account(session, account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return list(
        await settings_repo.list_contexts_for_account(session, account_id)
    )


@router.post("/api/accounts/{account_id}/contexts/{context_id}")
async def link_account_context(
    account_id: str,
    context_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create the account↔context link (idempotent)."""
    link = await settings_repo.link_account_context(
        session, account_id=account_id, context_id=context_id
    )
    if link is None:
        raise HTTPException(
            status_code=404, detail="Account or context not found"
        )
    return {"linked": True, "account_id": account_id, "context_id": context_id}


@router.delete("/api/accounts/{account_id}/contexts/{context_id}")
async def unlink_account_context(
    account_id: str,
    context_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove the account↔context link."""
    deleted = await settings_repo.unlink_account_context(
        session, account_id=account_id, context_id=context_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"unlinked": True, "account_id": account_id, "context_id": context_id}
