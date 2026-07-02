"""Persistence for ``core.contacts`` + ``core.contact_domains``."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import Contact, ContactDomain


def _domain_of(email: str) -> Optional[str]:
    """Best-effort domain extractor (everything after ``@``)."""
    if "@" not in email:
        return None
    return email.split("@", 1)[1].lower().strip() or None


async def list_contacts(
    session: AsyncSession, *, limit: int = 200
) -> Sequence[Contact]:
    """Return contacts ordered alphabetically by email."""
    stmt = select(Contact).order_by(Contact.email).limit(max(1, min(limit, 1000)))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_contact_by_email(
    session: AsyncSession, email: str
) -> Optional[Contact]:
    """Fetch a contact by email (citext column → case-insensitive lookup)."""
    stmt = select(Contact).where(Contact.email == email).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_domain_tier(
    session: AsyncSession, domain: str
) -> Optional[ContactDomain]:
    """Return the partner/blocked tier registered for a domain (or ``None``)."""
    return await session.get(ContactDomain, domain.lower())


async def resolve_tier(
    session: AsyncSession, email: Optional[str]
) -> str:
    """Resolve the tier for an email address.

    Resolution order:
        1. Exact-match contact row → ``Contact.tier``.
        2. Domain match in ``contact_domains`` → ``ContactDomain.tier``.
        3. Fallback → ``"unknown"``.
    """
    if not email:
        return "unknown"
    contact = await get_contact_by_email(session, email)
    if contact is not None:
        return contact.tier or "unknown"
    domain = _domain_of(email)
    if domain:
        match = await get_domain_tier(session, domain)
        if match is not None:
            return match.tier or "unknown"
    return "unknown"


async def upsert_contact_tier(
    session: AsyncSession,
    *,
    email: str,
    tier: str,
    display_name: Optional[str] = None,
) -> Contact:
    """Insert / update a contact's tier in one call."""
    existing = await get_contact_by_email(session, email)
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.tier = tier
        if display_name and not existing.display_name:
            existing.display_name = display_name
        existing.updated_at = now
        await session.flush()
        return existing
    contact = Contact(
        id=uuid.uuid4(),
        email=email,
        display_name=display_name,
        domain=_domain_of(email),
        tier=tier,
        interaction_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(contact)
    await session.flush()
    return contact


async def upsert_domain_tier(
    session: AsyncSession, *, domain: str, tier: str
) -> ContactDomain:
    """Insert / update a domain tier (``partner``/``blocked``/``unknown``)."""
    domain = domain.lower().strip()
    existing = await session.get(ContactDomain, domain)
    if existing is not None:
        existing.tier = tier
        await session.flush()
        return existing
    row = ContactDomain(domain=domain, tier=tier)
    session.add(row)
    await session.flush()
    return row
