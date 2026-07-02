"""Tests for the per-request access-log middleware (U6)."""

import logging
import re

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_access_log_records_status_and_path(
    app_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 200 GET emits one line on ``mission_control_v2.access`` at INFO."""
    caplog.set_level(logging.INFO, logger="mission_control_v2.access")

    response = await app_client.get("/api/info")
    assert response.status_code == 200

    access_records = [
        r for r in caplog.records if r.name == "mission_control_v2.access"
    ]
    assert access_records, "no access log line emitted"
    message = access_records[-1].getMessage()
    assert '"GET /api/info"' in message
    assert " 200 " in message
    assert re.search(r"\d+(?:\.\d+)?ms", message), message


@pytest.mark.integration
async def test_access_log_records_404(
    app_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 404 response is logged with the original status code."""
    caplog.set_level(logging.INFO, logger="mission_control_v2.access")

    response = await app_client.get("/no-such-route")
    assert response.status_code == 404

    access_records = [
        r for r in caplog.records if r.name == "mission_control_v2.access"
    ]
    assert any(' 404 ' in r.getMessage() for r in access_records)
