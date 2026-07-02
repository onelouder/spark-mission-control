"""Persistence for ``core.email_triage``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import EmailTriage


async def list_triage(
    session: AsyncSession,
    *,
    account_id: Optional[str] = None,
    context_id: Optional[str] = None,
    decision: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[EmailTriage]:
    """Return triage rows with optional filters, newest-first.

    Args:
        session: Active async session.
        account_id: Restrict to a single email account.
        context_id: Restrict to a single life-domain context.
        decision: Restrict to a specific ``final_decision`` value.
        limit: Maximum rows (clamped to ``[1, 500]``).
        offset: Pagination offset.
    """
    stmt = select(EmailTriage).order_by(desc(EmailTriage.received_at))
    if account_id:
        stmt = stmt.where(EmailTriage.account_id == account_id)
    if context_id:
        stmt = stmt.where(EmailTriage.context_id == context_id)
    if decision:
        stmt = stmt.where(EmailTriage.final_decision == decision)
    stmt = stmt.limit(max(1, min(limit, 500))).offset(max(0, offset))
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_triage(
    session: AsyncSession,
    *,
    account_id: Optional[str] = None,
    context_id: Optional[str] = None,
    decision: Optional[str] = None,
) -> int:
    """Aggregate count for the same filters as :func:`list_triage`."""
    stmt = select(func.count()).select_from(EmailTriage)
    if account_id:
        stmt = stmt.where(EmailTriage.account_id == account_id)
    if context_id:
        stmt = stmt.where(EmailTriage.context_id == context_id)
    if decision:
        stmt = stmt.where(EmailTriage.final_decision == decision)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_triage(session: AsyncSession, email_id: str) -> Optional[EmailTriage]:
    """Fetch a single triage row by id."""
    return await session.get(EmailTriage, email_id)


async def update_decision(
    session: AsyncSession,
    email_id: str,
    *,
    final_decision: str,
    filter_reason: Optional[str] = None,
    briefing_handled: Optional[bool] = None,
) -> Optional[EmailTriage]:
    """Update the decision fields on a triage row."""
    row = await session.get(EmailTriage, email_id)
    if row is None:
        return None
    row.final_decision = final_decision
    if filter_reason is not None:
        row.filter_reason = filter_reason
    if briefing_handled is not None:
        row.briefing_handled = briefing_handled
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def list_for_briefing(
    session: AsyncSession,
    *,
    decisions: tuple[str, ...] = ("decision", "review"),
    limit: int = 50,
) -> Sequence[EmailTriage]:
    """Return rows the briefing's *decisions* block should surface.

    Excludes any row already marked ``briefing_handled`` so the user
    doesn't see the same email twice.
    """
    stmt = (
        select(EmailTriage)
        .where(
            EmailTriage.final_decision.in_(decisions),
            EmailTriage.briefing_handled.is_(False),
        )
        .order_by(desc(EmailTriage.received_at))
        .limit(max(1, min(limit, 500)))
    )
    result = await session.execute(stmt)
    return result.scalars().all()
