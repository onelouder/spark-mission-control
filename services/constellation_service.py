"""OpenClaw constellation overview service."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from repositories import queue_repo
from services import openclaw_client


async def overview(session: AsyncSession) -> dict[str, Any]:
    """Return gateway, agent, queue, and config state for the constellation."""
    items = await queue_repo.list_items(session)
    gateway = await openclaw_client.gateway_health()
    return {
        "gateway": {
            "url": openclaw_client.gateway_url(),
            **gateway,
        },
        "agents": _agent_rows(items),
        "queue": _queue_summary(items),
        "config": _config_summary(),
    }


def _agent_rows(items) -> list[dict[str, Any]]:
    rows = []
    for agent_id, info in openclaw_client.AGENT_REGISTRY.items():
        assigned = [item for item in items if item.agent_id == agent_id]
        active = [
            item
            for item in assigned
            if item.column == "active" or item.session_status in {"running", "pending"}
        ]
        rows.append(
            {
                "id": agent_id,
                "name": info["name"],
                "session_key": info["session_key"],
                "assigned": len(assigned),
                "active": len(active),
                "running": sum(1 for item in assigned if item.session_status == "running"),
                "pending": sum(1 for item in assigned if item.session_status == "pending"),
            }
        )
    return rows


def _queue_summary(items) -> dict[str, Any]:
    by_column = Counter(item.column for item in items)
    by_status = Counter(item.session_status or "none" for item in items)
    return {
        "total": len(items),
        "by_column": dict(sorted(by_column.items())),
        "by_session_status": dict(sorted(by_status.items())),
    }


def _config_summary() -> dict[str, Any]:
    config_dir = get_settings().openclaw_config_dir
    if config_dir is None:
        return {
            "source": None,
            "status": "not_configured",
            "editable": False,
        }
    return {
        "source": str(config_dir),
        "status": "configured",
        "editable": False,
    }
