"""Health and system routes."""

import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from cache.redis_client import ping_redis
from config import get_settings
from db.session import get_engine
from services import openclaw_client, projectbox_client, surface_registry
from services.synapse_hub import HUB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

# Gateway health probe cache. The health badge polls /api/health every 30s
# from every open tab; without this each request dialed a short-lived
# gateway WebSocket. The hub's persistent connection answers for free; the
# probe only runs (and is then cached) when the hub is not running.
_GATEWAY_HEALTH_TTL = 30.0
_gateway_health_cache: dict = {"at": 0.0, "value": None}


async def _gateway_status() -> dict:
    """Gateway health keyed off the shared hub, with a cached probe fallback.

    Semantics are explicit: Mission Control talks to the gateway over
    WebSocket only, so ``transport`` says what was actually checked — this
    is not a statement about the gateway's (separately flaky) HTTP health.
    """
    if HUB._running:
        return {
            "status": "ok" if HUB.gateway.is_connected else "down",
            "transport": "websocket",
            "via": "hub",
        }
    now = time.monotonic()
    if (
        _gateway_health_cache["value"] is not None
        and now - _gateway_health_cache["at"] < _GATEWAY_HEALTH_TTL
    ):
        return _gateway_health_cache["value"]
    probe = await openclaw_client.gateway_health()
    value = {
        "status": probe["status"],
        "transport": "websocket",
        "via": "probe",
        **({"detail": probe["detail"]} if probe.get("detail") else {}),
    }
    _gateway_health_cache["value"] = value
    _gateway_health_cache["at"] = now
    return value


@router.get("/api/health")
async def health_check() -> dict:
    """Health check for Postgres and Redis."""
    checks = {
        "mission_control_v2": "ok",
        "postgres": "unknown",
        "redis": "unknown",
    }

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        logger.exception("Postgres health check failed")
        checks["postgres"] = "down"

    if await ping_redis():
        checks["redis"] = "ok"
    else:
        logger.warning("Redis health check failed (ping returned false)")
        checks["redis"] = "down"

    pb = await projectbox_client.health()
    checks["projectbox"] = "ok" if pb.get("reachable") else "down"

    gw = await _gateway_status()
    checks["openclaw"] = gw["status"]

    core_ok = (
        checks["postgres"] == "ok"
        and checks["redis"] == "ok"
        and checks["projectbox"] == "ok"
    )
    gateway_down = checks["openclaw"] == "down"
    overall = "ok" if core_ok and not gateway_down else "degraded"
    return {"status": overall, "checks": checks, "gateway": gw}


@router.get("/api/info")
async def info() -> dict:
    """Application metadata.

    The root path serves the Mission Control hub (tasks → Project-Box).
    JSON clients use this endpoint for identity and integration URLs.
    """
    settings = get_settings()
    pb_url = settings.projectbox_public_url or settings.projectbox_url
    surfaces = surface_registry.nav_surfaces(settings)
    return {
        "app": "mission-control-v2",
        "url": settings.public_base_url,
        "docs": "/docs",
        "health": "/api/health",
        "tasks": {
            "source": "projectbox",
            "ui": pb_url,
            "api": "/api/projectbox/tasks",
        },
        "crm": {
            "source": "twenty",
            "ui": settings.twenty_crm_public_url or settings.twenty_crm_url,
            "redirect": "/crm",
        },
        "constellation": {
            "source": "openclaw",
            "ui": "/constellation",
            "api": "/api/openclaw/constellation",
        },
        "surfaces": [
            {
                "id": surface["id"],
                "label": surface["label"],
                "kind": surface["kind"],
                "href": surface["href"],
                "external_url": surface.get("external_url"),
            }
            for surface in surfaces
        ],
        "openclaw": {
            "gateway": openclaw_client.gateway_url(),
            "dispatch": "/api/queue/{id}/dispatch",
            "agents": list(openclaw_client.AGENT_REGISTRY.keys()),
        },
        "deprecated": {
            "kanban_api": "Use /api/projectbox/tasks instead of kanban.tasks",
        },
    }
