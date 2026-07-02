"""Sprint 4 — accounts / contexts / accomplishments CRUD tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_account_crud_round_trip(app_client: AsyncClient) -> None:
    """Create → fetch → patch → delete an account."""
    payload = {
        "id": "acct-test",
        "name": "Test Inbox",
        "email": "test@example.com",
        "provider": "gmail",
    }
    created = await app_client.post("/api/accounts", json=payload)
    assert created.status_code == 201

    listed = await app_client.get("/api/accounts")
    assert any(r["id"] == "acct-test" for r in listed.json())

    patched = await app_client.patch(
        "/api/accounts/acct-test", json={"name": "Renamed"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    deleted = await app_client.delete("/api/accounts/acct-test")
    assert deleted.status_code == 200

    missing = await app_client.get("/api/accounts/acct-test")
    assert missing.status_code == 404


@pytest.mark.integration
async def test_context_crud_and_account_link(app_client: AsyncClient) -> None:
    """Contexts CRUD plus account ↔ context link/unlink."""
    await app_client.post(
        "/api/contexts",
        json={"id": "venture", "name": "Venture"},
    )
    await app_client.post(
        "/api/accounts",
        json={
            "id": "venture-mail",
            "name": "Venture Mail",
            "email": "ops@example.com",
            "provider": "gmail",
        },
    )

    linked = await app_client.post(
        "/api/accounts/venture-mail/contexts/venture"
    )
    assert linked.status_code == 200
    assert linked.json()["linked"] is True

    listed = await app_client.get("/api/accounts/venture-mail/contexts")
    assert "venture" in listed.json()

    # Idempotent re-link.
    again = await app_client.post("/api/accounts/venture-mail/contexts/venture")
    assert again.status_code == 200

    unlinked = await app_client.delete(
        "/api/accounts/venture-mail/contexts/venture"
    )
    assert unlinked.status_code == 200

    # 404 on a non-existent link.
    missing = await app_client.delete(
        "/api/accounts/venture-mail/contexts/venture"
    )
    assert missing.status_code == 404


@pytest.mark.integration
async def test_accomplishment_logging(app_client: AsyncClient) -> None:
    """Create + list + delete accomplishments."""
    created = await app_client.post(
        "/api/accomplishments",
        json={"text": "Shipped Sprint 4 polish", "source": "manual"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["text"] == "Shipped Sprint 4 polish"
    assert body["source"] == "manual"

    listed = await app_client.get("/api/accomplishments")
    assert any(
        a["text"] == "Shipped Sprint 4 polish" for a in listed.json()
    )

    deleted = await app_client.delete(f"/api/accomplishments/{body['id']}")
    assert deleted.status_code == 200

    # Second delete is 404.
    again = await app_client.delete(f"/api/accomplishments/{body['id']}")
    assert again.status_code == 404


def test_parity_diff_pairs_are_well_formed() -> None:
    """Smoke-check the parity script's URL pairs don't accidentally drift."""
    from scripts import parity_diff

    for v1, v2 in parity_diff.PAIRS:
        assert v1 is None or v1.startswith("/api/"), v1
        assert v2 is None or v2.startswith("/api/"), v2
        # At least one side must be present per row.
        assert v1 or v2
