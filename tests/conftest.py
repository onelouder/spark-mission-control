"""Test fixtures for Mission Control v2.

Strategy:
    - Reuse the docker-compose Postgres on port 5433 with a dedicated test
      database (``mission_control_test``).
    - Reuse the docker-compose Redis on port 6380, isolated to DB index 15.
    - Use ``NullPool`` on the test engine so asyncpg never holds idle
      connections across event loops (Python 3.14 + pytest-asyncio combo
      otherwise raises ``RuntimeError: Event loop is closed`` on teardown).
    - The schema is created once per session via ``Base.metadata.create_all``;
      every test then truncates table data so tests are independent.

Requires Docker services to be running:
    docker compose up -d
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB_URL = os.environ.setdefault(
    "MISSION_CONTROL_TEST_DATABASE_URL",
    "postgresql+asyncpg://mission_control:mission_control@"
    "localhost:5433/mission_control_test",
)
TEST_REDIS_URL = os.environ.setdefault(
    "MISSION_CONTROL_TEST_REDIS_URL",
    "redis://localhost:6380/15",
)

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ["MOLTBOT_GATEWAY_WS_URL"] = ""
os.environ["MOLTBOT_TOKEN"] = ""

from config import get_settings  # noqa: E402
from db import base as db_base  # noqa: E402
from db.orm import (  # noqa: E402,F401  (import for table registration)
    Account,
    AccountContext,
    Accomplishment,
    AgentProject,
    AppSetting,
    Contact,
    ContactDomain,
    Context,
    DispatchJob,
    EmailTriage,
    Project,
    QueueItem,
    SnoozeItem,
    Task,
)

# Tables in dependency order — children first so TRUNCATE CASCADE works
# cleanly even if FK constraints are deferred. ``CASCADE`` covers the rest.
TRUNCATABLE_TABLES = [
    "core.email_triage",
    "core.snooze_items",
    "core.account_contexts",
    "core.accounts",
    "core.contacts",
    "core.contact_domains",
    "core.app_settings",
    "agents.dispatch_jobs",
    "agents.queue_items",
    "agents.agent_projects",
    "kanban.accomplishments",
    "kanban.tasks",
    "kanban.projects",
    "core.contexts",
]


def _admin_dsn(test_dsn: str) -> str:
    """Return a DSN for the maintenance ``postgres`` database."""
    return test_dsn.rsplit("/", 1)[0] + "/postgres"


def _db_name(test_dsn: str) -> str:
    """Extract the database name from a SQLAlchemy DSN."""
    return test_dsn.rsplit("/", 1)[1]


async def _ensure_test_database(test_dsn: str) -> None:
    """Create the test database if it does not exist."""
    admin = create_async_engine(
        _admin_dsn(test_dsn),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": _db_name(test_dsn)},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{_db_name(test_dsn)}"'))
    finally:
        await admin.dispose()


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped async engine pointed at the test database.

    Uses ``NullPool`` so connections are opened/closed per operation,
    avoiding asyncpg's cross-event-loop teardown issues on Python 3.14.
    """
    await _ensure_test_database(TEST_DB_URL)

    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS kanban"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS agents"))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "citext"'))
        await conn.run_sync(db_base.Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(db_base.Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_between_tests(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate all tables before each test for guaranteed isolation."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(TRUNCATABLE_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped async session.

    Each test gets its own short-lived session; ``NullPool`` ensures the
    underlying connection is released cleanly on exit.
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator:
    """Yield a Redis client bound to test DB 15 and flush it on teardown."""
    import redis.asyncio as redis

    client = redis.from_url(
        TEST_REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        await client.flushdb()
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest_asyncio.fixture
async def app_client(
    engine: AsyncEngine, redis_client
) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client with the production DB session swapped for the test engine.

    Each request gets a fresh ``AsyncSession`` against the test database
    via FastAPI's dependency override. The production code path is
    exercised end-to-end.
    """
    get_settings.cache_clear()

    from services import auth_service

    auth_service.configure_auth()

    from db.session import get_session
    from main import app

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
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


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset the lru_cache on get_settings between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_projectbox(monkeypatch):
    """In-memory stand-in for the Project-Box API.

    Tests that exercise the wire layer of ``projectbox_client`` should
    override these by re-patching the same attribute (the autouse
    fixture is applied first; the test's explicit patch wins).
    """
    from datetime import datetime, timezone

    from services import projectbox_client
    from services.projectbox_client import ProjectBoxOffline
    from schemas.projectbox import ProjectBoxTask

    storage: dict[str, ProjectBoxTask] = {}

    def _new_task(title: str) -> ProjectBoxTask:
        now = datetime.now(timezone.utc)
        return ProjectBoxTask(
            id=f"{title}.md",
            title=title,
            status="open",
            priority="normal",
            scheduled=now.date().isoformat(),
            dateCreated=now,
            dateModified=now,
            tags=["task"],
        )

    async def _list_tasks(*, use_cache: bool = True):
        return list(storage.values())

    async def _create_task(title: str):
        task = _new_task(title)
        storage[task.id] = task
        return task

    async def _get_task(task_id: str):
        return storage.get(task_id)

    async def _update_task(task_id, updates):
        existing = storage.get(task_id)
        if existing is None:
            import httpx

            raise httpx.HTTPStatusError(
                "missing",
                request=httpx.Request("PUT", task_id),
                response=httpx.Response(404),
            )
        patch = updates.to_projectbox_payload()
        merged = existing.model_dump()
        merged.update(patch)
        merged["dateModified"] = datetime.now(timezone.utc)
        updated = ProjectBoxTask.model_validate(merged)
        storage[task_id] = updated
        return updated

    async def _archive_task(task_id: str):
        storage.pop(task_id, None)
        return {"success": True, "archivedAs": task_id}

    async def _add_time_entry(task_id, entry):
        existing = storage.get(task_id)
        if existing is None:
            raise ProjectBoxOffline(f"task {task_id} missing")
        existing.timeEntries.append(entry)  # type: ignore[arg-type]
        existing.dateModified = datetime.now(timezone.utc)
        return {"success": True, "task": existing.model_dump()}

    async def _health():
        return {
            "configured": True,
            "reachable": True,
            "url": "stub://projectbox",
            "task_count": len(storage),
        }

    monkeypatch.setattr(projectbox_client, "list_tasks", _list_tasks)
    monkeypatch.setattr(projectbox_client, "create_task", _create_task)
    monkeypatch.setattr(projectbox_client, "get_task", _get_task)
    monkeypatch.setattr(projectbox_client, "update_task", _update_task)
    monkeypatch.setattr(projectbox_client, "archive_task", _archive_task)
    monkeypatch.setattr(projectbox_client, "add_time_entry", _add_time_entry)
    monkeypatch.setattr(projectbox_client, "health", _health)

    return storage
