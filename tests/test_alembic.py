"""Verify the Alembic migration can build the schema from scratch (H2)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DB_URL, _ensure_test_database

EXPECTED_TABLES: dict[str, set[str]] = {
    "core": {
        "contexts",
        "accounts",
        "account_contexts",
        "contacts",
        "contact_domains",
        "app_settings",
        "snooze_items",
        "email_triage",
    },
    "kanban": {"projects", "tasks", "accomplishments"},
    "agents": {"agent_projects", "queue_items", "dispatch_jobs"},
}


@pytest.mark.integration
async def test_metadata_create_all_succeeds_on_empty_db() -> None:
    """Build the full schema graph (including cross-schema FKs) end-to-end.

    Mirrors what ``alembic upgrade head`` does in production. Run against a
    dedicated database so we do not collide with the per-test session
    fixture.
    """
    fresh_db = TEST_DB_URL.rsplit("/", 1)[0] + "/mission_control_alembic_test"
    await _ensure_test_database(fresh_db)

    eng = create_async_engine(fresh_db, echo=False)
    try:
        async with eng.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS kanban"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS agents"))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "citext"'))

            from db.base import Base
            from db.orm import (  # noqa: F401  (import for registration)
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

            await conn.run_sync(Base.metadata.create_all)

        async with eng.connect() as conn:
            for schema, expected in EXPECTED_TABLES.items():
                rows = await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :s"
                    ),
                    {"s": schema},
                )
                actual = {r[0] for r in rows}
                missing = expected - actual
                assert not missing, (
                    f"Schema {schema!r} missing tables: {missing}"
                )

        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP SCHEMA IF EXISTS agents CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS kanban CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
    finally:
        await eng.dispose()
