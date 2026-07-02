#!/usr/bin/env python3
"""One-time migration from mission-control v1 JSON files to PostgreSQL.

Usage:
    cd mission-control-v2
    source venv/bin/activate
    alembic upgrade head
    python scripts/migrate_json_to_pg.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.orm.agents import AgentProject, QueueItem
from db.orm.core import Account, AccountContext, AppSetting, Context
from db.orm.kanban import Task
from db.session import get_session_factory
from logging_config import configure_logging

configure_logging()
logger = logging.getLogger("mission_control_v2.migrate")

ACCOUNT_KNOWN_KEYS = frozenset(
    {
        "id",
        "name",
        "email",
        "provider",
        "icon",
        "color",
        "gateway_url",
        "tokens_path",
        "enabled",
        "contexts",
    }
)


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string (with optional ``Z`` suffix) into a datetime."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _coerce_uuid(raw: str) -> uuid.UUID:
    """Return a deterministic UUID for any v1 task id string.

    v1 used a mix of native UUIDs and short string ids. To preserve
    referential identity across re-runs, any non-UUID string is hashed
    into the ``NAMESPACE_OID`` UUIDv5 space.

    Args:
        raw: The v1 task id (may be UUID or arbitrary string).

    Returns:
        A valid UUID; identical for the same input every run.
    """
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        derived = uuid.uuid5(uuid.NAMESPACE_OID, str(raw))
        logger.warning(
            "Non-UUID v1 task id %r mapped to %s via uuid5(NAMESPACE_OID)",
            raw,
            derived,
        )
        return derived


async def migrate_contexts(session: AsyncSession, data_dir: Path, dry_run: bool) -> int:
    path = data_dir / "contexts.json"
    if not path.exists():
        return 0
    raw = json.loads(path.read_text())
    count = 0
    for ctx in raw.get("contexts", {}).values():
        row = Context(
            id=ctx["id"],
            name=ctx["name"],
            icon=ctx.get("icon"),
            color=ctx.get("color"),
            provider=ctx.get("provider"),
            user_email=ctx.get("user_email"),
            enabled=ctx.get("enabled", True),
            match_rules=ctx.get("match_rules", {}),
        )
        if not dry_run:
            await session.merge(row)
        count += 1
    return count


async def migrate_accounts(session: AsyncSession, data_dir: Path, dry_run: bool) -> int:
    """Migrate v1 ``accounts.json`` into ``core.accounts`` + ``core.account_contexts``.

    Unknown v1 fields (anything not in :data:`ACCOUNT_KNOWN_KEYS`) are
    deliberately preserved in the ``settings`` JSONB column so we do not
    silently drop forward-looking v1 metadata. Any new field added to v1
    after this script will land in ``settings`` until the schema is
    explicitly extended.
    """
    path = data_dir / "accounts.json"
    if not path.exists():
        return 0
    raw = json.loads(path.read_text())
    count = 0
    for acct in raw.get("accounts", {}).values():
        extra_settings = {
            k: v for k, v in acct.items() if k not in ACCOUNT_KNOWN_KEYS
        }
        if extra_settings:
            logger.info(
                "Account %s carries %d extra v1 field(s) into settings JSONB: %s",
                acct.get("id"),
                len(extra_settings),
                sorted(extra_settings),
            )
        row = Account(
            id=acct["id"],
            name=acct["name"],
            email=acct["email"],
            provider=acct["provider"],
            icon=acct.get("icon"),
            color=acct.get("color"),
            gateway_url=acct.get("gateway_url"),
            tokens_path=acct.get("tokens_path"),
            enabled=acct.get("enabled", True),
            settings=extra_settings,
        )
        if not dry_run:
            await session.merge(row)
        for ctx_id in acct.get("contexts", []):
            link = AccountContext(account_id=acct["id"], context_id=ctx_id)
            if not dry_run:
                await session.merge(link)
        count += 1
    return count


async def migrate_tasks(session: AsyncSession, data_dir: Path, dry_run: bool) -> int:
    path = data_dir / "tasks.json"
    if not path.exists():
        return 0
    tasks = json.loads(path.read_text())
    count = 0
    for item in tasks:
        task_id = _coerce_uuid(item["id"])
        row = Task(
            id=task_id,
            title=item["title"],
            description=item.get("description", ""),
            column_id=item.get("column", "unsorted"),
            position=item.get("position", 0),
            energy=item.get("energy"),
            source_type=item.get("source_type"),
            source_id=item.get("source_id"),
            source_url=item.get("source_url"),
            category=item.get("category"),
            notes=item.get("notes"),
            stuck_since=_parse_dt(item.get("stuck_since")),
            snoozed_until=_parse_dt(item.get("snoozed_until")),
            show_in_briefing=item.get("show_in_briefing", True),
            created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
            updated_at=_parse_dt(item.get("updated_at")) or datetime.now(timezone.utc),
        )
        if not dry_run:
            await session.merge(row)
        count += 1
    return count


async def migrate_queue(session: AsyncSession, data_dir: Path, dry_run: bool) -> int:
    path = data_dir / "queue.json"
    if not path.exists():
        return 0
    raw = json.loads(path.read_text())
    count = 0
    seen_projects: set[str] = set()

    for proj in raw.get("projects", []):
        pid = proj.get("id") or proj.get("name", "default")
        seen_projects.add(str(pid))
        row = AgentProject(
            id=str(pid),
            name=proj.get("name", str(pid)),
            description=proj.get("description"),
            status=proj.get("status", "active"),
        )
        if not dry_run:
            await session.merge(row)
        count += 1

    for item in raw.get("items", []):
        project_ref = item.get("project")
        if project_ref and str(project_ref) not in seen_projects:
            seen_projects.add(str(project_ref))
            stub = AgentProject(
                id=str(project_ref),
                name=str(project_ref),
                status="active",
            )
            if not dry_run:
                await session.merge(stub)
            count += 1

    for item in raw.get("items", []):
        row = QueueItem(
            id=item["id"],
            title=item["title"],
            description=item.get("description", ""),
            column=item.get("column", "queued"),
            project_id=item.get("project"),
            complexity=item.get("complexity", "medium"),
            agent_id=item.get("agent"),
            doc_path=item.get("doc_path"),
            session_id=item.get("session_id"),
            session_status=item.get("session_status"),
            priority=item.get("priority", 0),
            tags=item.get("tags") or [],
            notes=item.get("notes", ""),
            created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
            updated_at=_parse_dt(item.get("updated_at")) or datetime.now(timezone.utc),
            completed_at=_parse_dt(item.get("completed_at")),
        )
        if not dry_run:
            await session.merge(row)
        count += 1
    return count


async def migrate_config(session: AsyncSession, data_dir: Path, dry_run: bool) -> int:
    path = data_dir / "config.json"
    if not path.exists():
        return 0
    raw = json.loads(path.read_text())
    if not dry_run:
        await session.merge(AppSetting(key="app", value=raw))
    return 1


async def run_migration(dry_run: bool) -> None:
    """Run all migration steps."""
    settings = get_settings()
    data_dir = settings.v1_data_dir
    if not data_dir.is_dir():
        logger.error("v1 data dir not found: %s", data_dir)
        sys.exit(1)

    factory = get_session_factory()
    async with factory() as session:
        stats = {
            "contexts": await migrate_contexts(session, data_dir, dry_run),
            "accounts": await migrate_accounts(session, data_dir, dry_run),
            "config": await migrate_config(session, data_dir, dry_run),
            "tasks": await migrate_tasks(session, data_dir, dry_run),
            "queue": await migrate_queue(session, data_dir, dry_run),
        }
        if dry_run:
            await session.rollback()
            logger.info("DRY RUN — no changes committed")
        else:
            await session.commit()

    logger.info("Migration complete:")
    for key, val in stats.items():
        logger.info("  %s: %d", key, val)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate v1 JSON to PostgreSQL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing",
    )
    args = parser.parse_args()
    asyncio.run(run_migration(args.dry_run))


if __name__ == "__main__":
    main()
