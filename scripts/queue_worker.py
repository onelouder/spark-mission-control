#!/usr/bin/env python3
"""Deterministic queue worker for Mission Control v2."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.session import get_session_factory  # noqa: E402
from repositories import queue_repo  # noqa: E402
from schemas.queue import QueueItemUpdate  # noqa: E402
from services import dispatch_service, queue_service  # noqa: E402


RUN_LOG = ROOT / "data" / "queue_worker_runs.jsonl"
ARCHIVE_DONE_DAYS = 7
STALE_DAYS = 14
ACTIVE_DISPATCH_STATUSES = {"pending", "needs_update"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def append_note(existing: str | None, note: str, now: datetime) -> str:
    stamp = now.strftime("%Y-%m-%d %H:%M")
    return f"{existing or ''}\n---\n[{stamp}] {note}".lstrip()


async def route_items(session, *, dry_run: bool) -> list[dict[str, Any]]:
    rows = await queue_repo.list_items(session)
    candidates = [
        row for row in rows
        if row.column in {"queued", "urgent"}
        and not row.session_id
        and row.session_status not in {"running", "done"}
    ]
    candidates.sort(key=lambda row: (row.column != "urgent", -(row.priority or 0)))

    routed: list[dict[str, Any]] = []
    for row in candidates:
        item = queue_service.to_read(row)
        agent_id = item.agent or queue_service.suggest_agent_for_item(item)
        entry = {"id": item.id, "title": item.title, "agent": agent_id}
        if dry_run:
            routed.append({**entry, "status": "would_dispatch"})
            continue
        outcome = await dispatch_service.dispatch(
            session,
            queue_item_id=item.id,
            agent_id=agent_id,
        )
        if outcome and outcome.success:
            routed.append({
                **entry,
                "status": "queued_offline" if outcome.offline else "dispatched",
                "run_id": outcome.run_id,
                "job_id": outcome.job.id,
            })
        else:
            routed.append({
                **entry,
                "status": "error",
                "error": (outcome.error if outcome else "item not found"),
                "job_id": outcome.job.id if outcome else None,
            })
    return routed


async def retry_pending_items(session, *, dry_run: bool) -> list[dict[str, Any]]:
    rows = await queue_repo.list_items(session)
    candidates = [
        row for row in rows
        if row.column == "active"
        and row.session_status in ACTIVE_DISPATCH_STATUSES
        and row.agent_id
        and (not row.session_id or row.session_status == "needs_update")
    ]
    retried: list[dict[str, Any]] = []
    for row in candidates:
        entry = {"id": row.id, "title": row.title, "agent": row.agent_id}
        if dry_run:
            retried.append({**entry, "status": f"would_{row.session_status}"})
            continue
        outcome = await dispatch_service.dispatch(
            session,
            queue_item_id=row.id,
            agent_id=row.agent_id,
        )
        if outcome and outcome.success:
            retried.append({
                **entry,
                "status": "queued_offline" if outcome.offline else "dispatched",
                "run_id": outcome.run_id,
                "job_id": outcome.job.id,
            })
        else:
            retried.append({
                **entry,
                "status": "error",
                "error": (outcome.error if outcome else "item not found"),
                "job_id": outcome.job.id if outcome else None,
            })
    return retried


async def archive_old_done(session, *, dry_run: bool, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=ARCHIVE_DONE_DAYS)
    archived: list[dict[str, Any]] = []
    for row in await queue_repo.list_items(session):
        if row.column not in {"done", "review"}:
            continue
        if row.column == "review" and row.session_status != "done":
            continue
        completed_at = as_utc(row.completed_at) or as_utc(row.updated_at)
        if completed_at and completed_at <= cutoff:
            archived.append({"id": row.id, "title": row.title, "completed_at": completed_at.isoformat()})
            if not dry_run:
                await queue_service.update(session, row.id, QueueItemUpdate(column="archive"))
    return archived


async def flag_stale_active(session, *, dry_run: bool, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=STALE_DAYS)
    marker = f"[QUEUE WORKER {now.date().isoformat()}]"
    flagged: list[dict[str, Any]] = []
    for row in await queue_repo.list_items(session):
        if row.column != "active":
            continue
        updated_at = as_utc(row.updated_at) or as_utc(row.created_at)
        if not updated_at or updated_at > cutoff:
            continue
        if marker in (row.notes or ""):
            continue
        note = f"{marker} Active task is stale: no queue update for >= {STALE_DAYS} days."
        flagged.append({"id": row.id, "title": row.title, "agent": row.agent_id, "updated_at": updated_at.isoformat()})
        if not dry_run:
            await queue_service.update(
                session,
                row.id,
                QueueItemUpdate(notes=append_note(row.notes, note, now)),
            )
    return flagged


def summarize(results: dict[str, Any]) -> str:
    lines = [
        "Queue Worker Summary",
        f"- Routed queued/urgent: {len(results['routed'])}",
        f"- Retried pending: {len(results['retried'])}",
        f"- Archived old done: {len(results['archived'])}",
        f"- Flagged stale active: {len(results['flagged'])}",
    ]
    for group in ("routed", "retried", "archived", "flagged"):
        for item in results[group]:
            label = item.get("title") or item.get("id")
            status = item.get("status") or group.rstrip("d")
            agent = f" -> {item['agent']}" if item.get("agent") else ""
            lines.append(f"  - {status}: {label}{agent}")
            if item.get("error"):
                lines.append(f"    error: {item['error']}")
    return "\n".join(lines)


async def run(*, dry_run: bool) -> dict[str, Any]:
    now = utc_now()
    factory = get_session_factory()
    async with factory() as session:
        try:
            results = {
                "ran_at": now.isoformat(),
                "dry_run": dry_run,
                "routed": await route_items(session, dry_run=dry_run),
                "retried": await retry_pending_items(session, dry_run=dry_run),
                "archived": await archive_old_done(session, dry_run=dry_run, now=now),
                "flagged": await flag_stale_active(session, dry_run=dry_run, now=now),
            }
            results["summary"] = summarize(results)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
                RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
                with RUN_LOG.open("a") as handle:
                    handle.write(json.dumps(results, sort_keys=True) + "\n")
            return results
        except Exception:
            await session.rollback()
            raise


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = await run(dry_run=args.dry_run)
    print(json.dumps(results, indent=2, sort_keys=True) if args.json else results["summary"])
    errors = [
        item for group in ("routed", "retried")
        for item in results[group]
        if item.get("status") == "error"
    ]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
