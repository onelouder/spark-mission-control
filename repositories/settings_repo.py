"""Persistence helpers for accounts, contexts, and the account↔context link."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import Account, AccountContext, Context


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


async def list_accounts(session: AsyncSession) -> Sequence[Account]:
    """Return all accounts, alpha by id."""
    result = await session.execute(select(Account).order_by(Account.id))
    return result.scalars().all()


async def get_account(session: AsyncSession, account_id: str) -> Optional[Account]:
    """Fetch an account by id."""
    return await session.get(Account, account_id)


async def create_account(
    session: AsyncSession, *, data: dict[str, Any]
) -> Account:
    """Insert a new account row."""
    now = _utc_now()
    payload = dict(data)
    account = Account(
        **payload,
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    await session.flush()
    return account


async def update_account(
    session: AsyncSession,
    account_id: str,
    *,
    changes: dict[str, Any],
) -> Optional[Account]:
    """Apply partial updates to an account row."""
    account = await session.get(Account, account_id)
    if account is None:
        return None
    for key, value in changes.items():
        if hasattr(account, key):
            setattr(account, key, value)
    account.updated_at = _utc_now()
    await session.flush()
    return account


async def delete_account(session: AsyncSession, account_id: str) -> bool:
    """Remove an account; ``False`` if missing."""
    account = await session.get(Account, account_id)
    if account is None:
        return False
    await session.delete(account)
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------


async def list_contexts(session: AsyncSession) -> Sequence[Context]:
    """Return contexts in alpha order."""
    result = await session.execute(select(Context).order_by(Context.id))
    return result.scalars().all()


async def get_context(session: AsyncSession, context_id: str) -> Optional[Context]:
    """Fetch a context by id."""
    return await session.get(Context, context_id)


async def create_context(
    session: AsyncSession, *, data: dict[str, Any]
) -> Context:
    """Insert a new context row."""
    now = _utc_now()
    context = Context(**data, created_at=now, updated_at=now)
    session.add(context)
    await session.flush()
    return context


async def update_context(
    session: AsyncSession,
    context_id: str,
    *,
    changes: dict[str, Any],
) -> Optional[Context]:
    """Apply partial updates to a context."""
    context = await session.get(Context, context_id)
    if context is None:
        return None
    for key, value in changes.items():
        if hasattr(context, key):
            setattr(context, key, value)
    context.updated_at = _utc_now()
    await session.flush()
    return context


async def delete_context(session: AsyncSession, context_id: str) -> bool:
    """Remove a context; ``False`` if missing."""
    context = await session.get(Context, context_id)
    if context is None:
        return False
    await session.delete(context)
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Account ↔ Context link
# ---------------------------------------------------------------------------


async def link_account_context(
    session: AsyncSession, *, account_id: str, context_id: str
) -> Optional[AccountContext]:
    """Create an account↔context link (idempotent).

    Returns ``None`` if either side is missing.
    """
    account = await session.get(Account, account_id)
    context = await session.get(Context, context_id)
    if account is None or context is None:
        return None

    existing = await session.get(AccountContext, (account_id, context_id))
    if existing is not None:
        return existing

    link = AccountContext(account_id=account_id, context_id=context_id)
    session.add(link)
    await session.flush()
    return link


async def unlink_account_context(
    session: AsyncSession, *, account_id: str, context_id: str
) -> bool:
    """Remove an account↔context link; ``False`` if missing."""
    link = await session.get(AccountContext, (account_id, context_id))
    if link is None:
        return False
    await session.delete(link)
    await session.flush()
    return True


async def list_contexts_for_account(
    session: AsyncSession, account_id: str
) -> Sequence[str]:
    """Return context ids linked to ``account_id``."""
    stmt = select(AccountContext.context_id).where(
        AccountContext.account_id == account_id
    )
    return [row[0] for row in (await session.execute(stmt)).all()]
