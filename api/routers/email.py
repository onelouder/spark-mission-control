"""Email triage HTTP routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from repositories import contact_repo, email_repo
from schemas.email import (
    ContactRead,
    ContactTierWrite,
    EmailDecision,
    EmailToTaskRequest,
    EmailTriageList,
    EmailTriageRead,
)
from services import briefing_service, email_service

router = APIRouter(tags=["email"])


@router.get("/api/emails", response_model=EmailTriageList)
async def list_emails(
    account_id: Optional[str] = Query(None),
    context_id: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> EmailTriageList:
    """Paginated list of triaged emails."""
    rows, total = await email_service.list_emails(
        session,
        account_id=account_id,
        context_id=context_id,
        decision=decision,
        limit=limit,
        offset=offset,
    )
    return EmailTriageList(items=rows, total=total)


@router.get("/api/emails/{email_id}", response_model=EmailTriageRead)
async def get_email(
    email_id: str,
    session: AsyncSession = Depends(get_session),
) -> EmailTriageRead:
    """Fetch one triage row."""
    row = await email_repo.get_triage(session, email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailTriageRead.model_validate(row)


@router.post("/api/emails/{email_id}/decision", response_model=EmailTriageRead)
async def set_email_decision(
    email_id: str,
    decision: EmailDecision,
    session: AsyncSession = Depends(get_session),
) -> EmailTriageRead:
    """Set a manual triage decision and invalidate today's briefing cache."""
    row = await email_service.apply_decision(session, email_id, decision)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    await briefing_service.invalidate_today()
    return row


@router.post("/api/emails/{email_id}/classify", response_model=EmailTriageRead)
async def classify_email(
    email_id: str,
    session: AsyncSession = Depends(get_session),
) -> EmailTriageRead:
    """Re-run the triage classifier against the current contact-tier data."""
    row = await email_service.auto_classify(session, email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    await briefing_service.invalidate_today()
    return row


@router.post("/api/emails/{email_id}/to-task")
async def email_to_task(
    email_id: str,
    payload: EmailToTaskRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Promote an email into a Project-Box task."""
    outcome = await email_service.convert_to_task(session, email_id, payload)
    if outcome is None:
        raise HTTPException(status_code=404, detail="Email not found")
    await briefing_service.invalidate_today()
    return outcome


# ---------------------------------------------------------------------------
# Contacts (tier management; lives in the same router for now)
# ---------------------------------------------------------------------------


@router.get("/api/contacts", response_model=list[ContactRead])
async def list_contacts(
    session: AsyncSession = Depends(get_session),
) -> list[ContactRead]:
    """List configured contacts (tier-bearing rows only)."""
    rows = await contact_repo.list_contacts(session)
    return [ContactRead.model_validate(r) for r in rows]


@router.post("/api/contacts/{email}/tier", response_model=ContactRead)
async def set_contact_tier(
    email: str,
    payload: ContactTierWrite,
    session: AsyncSession = Depends(get_session),
) -> ContactRead:
    """Upsert a contact's tier (``partner``/``blocked``/``unknown``/…)."""
    contact = await contact_repo.upsert_contact_tier(
        session, email=email, tier=payload.tier
    )
    await briefing_service.invalidate_today()
    return ContactRead.model_validate(contact)


@router.post("/api/contact-domains/{domain}/tier")
async def set_domain_tier(
    domain: str,
    payload: ContactTierWrite,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Upsert a *domain* tier (broad classifier for vendor newsletters)."""
    row = await contact_repo.upsert_domain_tier(
        session, domain=domain, tier=payload.tier
    )
    await briefing_service.invalidate_today()
    return {"domain": row.domain, "tier": row.tier}
