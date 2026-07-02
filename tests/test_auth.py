"""Auth middleware and login flow tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from config import get_settings
from services import auth_service


@pytest.fixture
def auth_enabled(monkeypatch):
    """Enable auth with a known test password for this module only."""
    password_hash = auth_service.hash_password("testpass")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("MISSION_CONTROL_USERNAME", "admin")
    monkeypatch.setenv("MISSION_CONTROL_PASSWORD_HASH", password_hash)
    get_settings.cache_clear()
    auth_service.configure_auth()
    yield
    get_settings.cache_clear()
    auth_service.configure_auth()


@pytest.fixture
async def authed_client(auth_enabled, engine, redis_client):
    """Client with auth enabled (overrides default AUTH_ENABLED=false)."""
    get_settings.cache_clear()
    auth_service.configure_auth()

    from db.session import get_session
    from main import app
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.integration
async def test_health_is_public_when_auth_enabled(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/health")
    assert response.status_code == 200


@pytest.mark.integration
async def test_api_requires_auth_when_enabled(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/briefing/today")
    assert response.status_code == 401


@pytest.mark.integration
async def test_login_grants_access(authed_client: AsyncClient) -> None:
    login = await authed_client.post(
        "/login",
        data={"username": "admin", "password": "testpass"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    token = login.cookies.get("session_token")
    assert token

    authed = await authed_client.get(
        "/api/briefing/today",
        cookies={"session_token": token},
    )
    assert authed.status_code == 200


@pytest.mark.integration
async def test_logout_clears_session(authed_client: AsyncClient) -> None:
    login = await authed_client.post(
        "/login",
        data={"username": "admin", "password": "testpass"},
        follow_redirects=False,
    )
    token = login.cookies.get("session_token")
    logout = await authed_client.get(
        "/logout",
        cookies={"session_token": token},
        follow_redirects=False,
    )
    assert logout.status_code == 302

    blocked = await authed_client.get(
        "/api/briefing/today",
        cookies={"session_token": token},
    )
    assert blocked.status_code == 401
