"""Sprint 3 — email triage + classifier tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import Account, Context, EmailTriage
from services import triage_service


@pytest.fixture
async def seed_accounts(db_session: AsyncSession) -> Tuple[str, str]:
    """Seed a context + account so EmailTriage rows can satisfy their FKs."""
    ctx = Context(id="venture", name="Venture", enabled=True, match_rules={})
    acct = Account(
        id="venture-primary",
        name="Venture Primary",
        email="ops@example.com",
        provider="gmail",
    )
    db_session.add(ctx)
    db_session.add(acct)
    await db_session.flush()
    await db_session.commit()
    return acct.id, ctx.id


async def _insert_triage(
    db_session: AsyncSession,
    *,
    email_id: str,
    account_id: str,
    decision: str = "review",
    from_address: str = "anon@example.com",
    subject: str = "Hello there",
    converted: bool = False,
) -> EmailTriage:
    """Helper: insert an EmailTriage row via the test session."""
    row = EmailTriage(
        id=email_id,
        account_id=account_id,
        subject=subject,
        from_address=from_address,
        from_name="Sender",
        received_at=datetime.now(timezone.utc),
        final_decision=decision,
        briefing_handled=False,
        converted_to_task=converted,
        analysis={},
        pipeline_stages={},
        processed_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.commit()
    return row


@pytest.mark.integration
async def test_classifier_partner_to_decision(
    app_client: AsyncClient, db_session: AsyncSession, seed_accounts
) -> None:
    """Partner-tier contact → ``decision`` verdict."""
    account_id, _ = seed_accounts
    await _insert_triage(
        db_session,
        email_id="msg-001",
        account_id=account_id,
        from_address="partner@example.com",
    )
    await app_client.post(
        "/api/contacts/partner@example.com/tier", json={"tier": "partner"}
    )

    response = await app_client.post("/api/emails/msg-001/classify")
    assert response.status_code == 200
    body = response.json()
    assert body["final_decision"] == triage_service.DECISION_BRIEF
    assert body["contact_tier"] == "partner"


@pytest.mark.integration
async def test_classifier_blocked_to_drop(
    app_client: AsyncClient, db_session: AsyncSession, seed_accounts
) -> None:
    """Blocked-tier contact → ``drop`` verdict."""
    account_id, _ = seed_accounts
    await _insert_triage(
        db_session,
        email_id="msg-002",
        account_id=account_id,
        from_address="spammer@junk.example",
    )
    await app_client.post(
        "/api/contact-domains/junk.example/tier", json={"tier": "blocked"}
    )
    response = await app_client.post("/api/emails/msg-002/classify")
    assert response.status_code == 200
    body = response.json()
    assert body["final_decision"] == triage_service.DECISION_DROP


@pytest.mark.integration
async def test_email_to_task_idempotent(
    app_client: AsyncClient, db_session: AsyncSession, seed_accounts
) -> None:
    """Converting twice returns the same task id and ``already_converted=True``."""
    account_id, _ = seed_accounts
    await _insert_triage(
        db_session,
        email_id="msg-003",
        account_id=account_id,
        from_address="customer@example.com",
        subject="Important request",
    )
    first = await app_client.post(
        "/api/emails/msg-003/to-task", json={"column": "today"}
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["task_id"]
    assert first_body["already_converted"] is False

    second = await app_client.post(
        "/api/emails/msg-003/to-task", json={"column": "today"}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["task_id"] == first_body["task_id"]
    assert second_body["already_converted"] is True

    # Triage row should be flagged converted.
    after = (await app_client.get("/api/emails/msg-003")).json()
    assert after["converted_to_task"] is True
    assert after["final_decision"] == triage_service.DECISION_TASK


@pytest.mark.integration
async def test_list_emails_filters(
    app_client: AsyncClient, db_session: AsyncSession, seed_accounts
) -> None:
    """Decision/account filters narrow the list."""
    account_id, _ = seed_accounts
    await _insert_triage(
        db_session, email_id="msg-101", account_id=account_id, decision="review"
    )
    await _insert_triage(
        db_session, email_id="msg-102", account_id=account_id, decision="drop"
    )

    review_list = (
        await app_client.get("/api/emails", params={"decision": "review"})
    ).json()
    drop_list = (
        await app_client.get("/api/emails", params={"decision": "drop"})
    ).json()

    review_ids = {r["id"] for r in review_list["items"]}
    drop_ids = {r["id"] for r in drop_list["items"]}
    assert "msg-101" in review_ids
    assert "msg-102" in drop_ids
    assert review_ids.isdisjoint(drop_ids)


def test_triage_pure_function_table() -> None:
    """Sanity-check the classifier without touching the database."""
    assert (
        triage_service.classify(
            contact_tier="partner", from_address="vip@partner.io"
        ).decision
        == triage_service.DECISION_BRIEF
    )
    assert (
        triage_service.classify(
            contact_tier="blocked", from_address="spam@bad.io"
        ).decision
        == triage_service.DECISION_DROP
    )
    assert (
        triage_service.classify(
            contact_tier="unknown",
            from_address="hello@example.com",
            subject="Weekly Newsletter Digest",
        ).decision
        == triage_service.DECISION_DROP
    )
    assert (
        triage_service.classify(
            contact_tier="unknown", from_address="someone@example.com"
        ).decision
        == triage_service.DECISION_REVIEW
    )
    assert (
        triage_service.classify(
            contact_tier="unknown", from_address=None, converted_to_task=True
        ).decision
        == triage_service.DECISION_TASK
    )
