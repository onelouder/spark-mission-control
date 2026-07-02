"""Business logic for email-triage endpoints.

Layers triage decisioning + contact-tier resolution on top of the
:mod:`repositories.email_repo` and :mod:`repositories.contact_repo`
modules.

Email → task conversion now lands tasks in **Project-Box** (the
Obsidian-backed Flow Focus app) rather than v2's legacy
``kanban.tasks`` table. The link is preserved by storing the
Project-Box filename inside ``EmailTriage.analysis["projectbox_filename"]``
so the v1 ``converted_task_id`` UUID column can remain untouched.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import contact_repo, email_repo
from schemas.email import EmailDecision, EmailTriageRead, EmailToTaskRequest
from services import projectbox_client, triage_service
from services.projectbox_client import ProjectBoxOffline

logger = logging.getLogger(__name__)


def _to_read(row) -> EmailTriageRead:
    """Build the API DTO from an ORM row (avoids repeating the mapping)."""
    return EmailTriageRead.model_validate(row)


async def list_emails(
    session: AsyncSession,
    *,
    account_id: Optional[str] = None,
    context_id: Optional[str] = None,
    decision: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[EmailTriageRead], int]:
    """Return (rows, total) tuple matching the supplied filters."""
    rows = await email_repo.list_triage(
        session,
        account_id=account_id,
        context_id=context_id,
        decision=decision,
        limit=limit,
        offset=offset,
    )
    total = await email_repo.count_triage(
        session, account_id=account_id, context_id=context_id, decision=decision
    )
    return [_to_read(r) for r in rows], total


async def apply_decision(
    session: AsyncSession, email_id: str, data: EmailDecision
) -> Optional[EmailTriageRead]:
    """Persist a manual decision on an email row."""
    row = await email_repo.update_decision(
        session,
        email_id,
        final_decision=data.final_decision,
        filter_reason=data.filter_reason,
        briefing_handled=data.briefing_handled,
    )
    return _to_read(row) if row else None


async def auto_classify(
    session: AsyncSession, email_id: str
) -> Optional[EmailTriageRead]:
    """Re-run the triage classifier against the current contact data.

    Useful after a contact tier changes (e.g. user manually flagged a
    domain as ``blocked``) — call this on an email row to recompute its
    ``final_decision`` without typing it out by hand.
    """
    row = await email_repo.get_triage(session, email_id)
    if row is None:
        return None
    tier = await contact_repo.resolve_tier(session, row.from_address)
    verdict = triage_service.classify(
        contact_tier=tier,
        from_address=row.from_address,
        subject=row.subject,
        filter_reason_hint=row.filter_reason,
        converted_to_task=row.converted_to_task,
    )
    row.contact_tier = tier
    row.final_decision = verdict.decision
    row.filter_reason = verdict.reason
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _to_read(row)


async def convert_to_task(
    session: AsyncSession,
    email_id: str,
    data: EmailToTaskRequest,
) -> Optional[dict]:
    """Promote a triage row into a Project-Box task.

    Returns ``{"task_id": filename, "email": EmailTriageRead,
    "already_converted": bool, "offline": bool}`` on success or ``None``
    if the email id does not exist. Idempotent — re-running against an
    already-converted email returns the existing pairing.

    Resilient when Project-Box is offline: the email row is *not*
    flagged converted, an ``offline=True`` flag is returned, and the
    caller can retry later. This preserves the user's task drift
    contract — emails never silently fall on the floor.
    """
    row = await email_repo.get_triage(session, email_id)
    if row is None:
        return None

    existing_filename = (row.analysis or {}).get("projectbox_filename")
    if row.converted_to_task and existing_filename:
        return {
            "task_id": existing_filename,
            "email": _to_read(row),
            "already_converted": True,
            "offline": False,
        }

    title = data.title or (row.subject or "(email)").strip()[:200]
    try:
        task = await projectbox_client.create_task(title)
    except ProjectBoxOffline as exc:
        logger.warning(
            "convert_to_task: Project-Box offline (%s); email %s left pending",
            exc,
            email_id,
        )
        return {
            "task_id": None,
            "email": _to_read(row),
            "already_converted": False,
            "offline": True,
            "error": str(exc),
        }

    now = datetime.now(timezone.utc)
    analysis = dict(row.analysis or {})
    analysis["projectbox_filename"] = task.id
    analysis["projectbox_created_at"] = now.isoformat()

    row.analysis = analysis
    row.converted_to_task = True
    row.final_decision = triage_service.DECISION_TASK
    row.briefing_handled = True
    row.updated_at = now
    await session.flush()

    return {
        "task_id": task.id,
        "email": _to_read(row),
        "already_converted": False,
        "offline": False,
    }
