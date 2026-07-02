"""Tests for the v1 → v2 migration script."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.orm.core import Account, AccountContext, Context
from db.orm.kanban import Task
from scripts.migrate_json_to_pg import (
    _coerce_uuid,
    migrate_accounts,
    migrate_contexts,
    migrate_tasks,
)


def test_coerce_uuid_passes_through_valid() -> None:
    """A valid UUID string is returned as-is."""
    original = uuid.uuid4()
    assert _coerce_uuid(str(original)) == original


def test_coerce_uuid_is_deterministic_for_non_uuid() -> None:
    """A non-UUID string maps to the same UUIDv5 every call."""
    first = _coerce_uuid("task-001")
    second = _coerce_uuid("task-001")
    assert first == second
    expected = uuid.uuid5(uuid.NAMESPACE_OID, "task-001")
    assert first == expected


def test_coerce_uuid_distinct_inputs_map_distinct(tmp_path: Path) -> None:
    """Different non-UUID inputs produce different UUIDs."""
    assert _coerce_uuid("task-001") != _coerce_uuid("task-002")


@pytest.fixture
def v1_data_dir(tmp_path: Path) -> Path:
    """Build a synthetic v1 ``data/`` directory for migration tests."""
    (tmp_path / "contexts.json").write_text(
        json.dumps(
            {
                "contexts": {
                    "venture": {
                        "id": "venture",
                        "name": "Venture",
                        "enabled": True,
                        "match_rules": {"domains": ["example.com"]},
                    }
                }
            }
        )
    )
    (tmp_path / "accounts.json").write_text(
        json.dumps(
            {
                "accounts": {
                    "venture-primary": {
                        "id": "venture-primary",
                        "name": "Venture Primary",
                        "email": "ops@example.com",
                        "provider": "gmail",
                        "enabled": True,
                        "contexts": ["venture"],
                        "custom_v1_field": "should_land_in_settings",
                    }
                }
            }
        )
    )
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": str(uuid.uuid4()),
                    "title": "Real UUID task",
                    "column": "today",
                    "position": 0,
                },
                {
                    "id": "legacy-string-id",
                    "title": "Non-UUID v1 task",
                    "column": "today",
                    "position": 1,
                },
            ]
        )
    )
    return tmp_path


@pytest.mark.integration
async def test_migrate_contexts_inserts_rows(
    db_session: AsyncSession, v1_data_dir: Path
) -> None:
    """``contexts.json`` is mapped into ``core.contexts``."""
    count = await migrate_contexts(db_session, v1_data_dir, dry_run=False)
    await db_session.flush()
    assert count == 1
    rows = (await db_session.execute(select(Context))).scalars().all()
    assert {r.id for r in rows} == {"venture"}


@pytest.mark.integration
async def test_migrate_accounts_preserves_unknown_fields(
    db_session: AsyncSession, v1_data_dir: Path
) -> None:
    """Unknown v1 fields land in ``Account.settings`` JSONB."""
    await migrate_contexts(db_session, v1_data_dir, dry_run=False)
    count = await migrate_accounts(db_session, v1_data_dir, dry_run=False)
    await db_session.flush()
    assert count == 1
    account = (
        await db_session.execute(select(Account))
    ).scalar_one()
    assert account.settings == {"custom_v1_field": "should_land_in_settings"}
    links = (
        await db_session.execute(select(AccountContext))
    ).scalars().all()
    assert {l.context_id for l in links} == {"venture"}


@pytest.mark.integration
async def test_migrate_tasks_handles_non_uuid_ids(
    db_session: AsyncSession, v1_data_dir: Path
) -> None:
    """Non-UUID task ids are coerced via uuid5 and persisted."""
    count = await migrate_tasks(db_session, v1_data_dir, dry_run=False)
    await db_session.flush()
    assert count == 2
    tasks = (await db_session.execute(select(Task))).scalars().all()
    derived = uuid.uuid5(uuid.NAMESPACE_OID, "legacy-string-id")
    assert derived in {t.id for t in tasks}


@pytest.mark.integration
async def test_dry_run_does_not_persist(
    db_session: AsyncSession, v1_data_dir: Path
) -> None:
    """Dry-run reports counts but writes no rows."""
    count = await migrate_contexts(db_session, v1_data_dir, dry_run=True)
    assert count == 1
    rows = (await db_session.execute(select(Context))).scalars().all()
    assert rows == []
