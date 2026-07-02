"""Synapse multi-agent chat and terminal WebSocket routes.

The WebSocket endpoint is a thin adapter onto :data:`services.synapse_hub.HUB`
— a single shared gateway connection multiplexed across all browser clients
(see ``services/synapse_hub.py``). REST endpoints prefer the hub's live
connection and fall back to ephemeral ``GatewayConnection`` dials when the
hub is offline (e.g. tests, gateway down).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from services import auth_service, openclaw_client, synapse_models, voice_bridge
from services.synapse_hub import (  # noqa: F401  (re-exported for tests/back-compat)
    HUB,
    _agent_statuses,
    _base_agent,
    _merge_session,
    _merge_sessions,
    _now,
    _session_key,
    _session_model,
    _session_model_override,
    _set_agent_model,
    _context_max,
    _estimated_context_used,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["synapse"])


@router.get("/api/synapse/fleet")
async def synapse_fleet() -> dict[str, Any]:
    """Return fleet status for the Synapse UI."""
    if HUB.gateway.is_connected:
        return {
            "agents": await HUB.agent_statuses(),  # shared cached snapshot
            "gateway": {"status": "ok"},
            "ts": _now(),
        }
    gateway = await openclaw_client.gateway_health()
    if gateway["status"] == "ok":
        agents = await _agent_statuses_from_gateway()
    else:
        agents = await _agent_statuses()
    return {
        "agents": agents,
        "gateway": gateway,
        "ts": _now(),
    }


@router.get("/api/synapse/hub/stats")
async def synapse_hub_stats() -> dict[str, Any]:
    """Operational counters for the shared Synapse hub."""
    return HUB.stats_snapshot()


@router.get("/api/synapse/models")
async def synapse_models_api() -> dict[str, Any]:
    """Return the OpenClaw model catalog used by Synapse model pickers."""
    return synapse_models.get_model_catalog().to_api_payload()


@router.put("/api/synapse/agent/{agent_id}/model")
async def synapse_set_agent_model(agent_id: str, request: Request) -> dict[str, Any]:
    """Set the session-scoped model override for an agent."""
    body = await request.json()
    gateway = HUB.gateway if HUB.gateway.is_connected else None
    result = await _set_agent_model(agent_id, str(body.get("model") or ""), gateway=gateway)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to set model")
    return result


@router.get("/api/sessions/list")
async def synapse_sessions_list() -> dict[str, Any]:
    """Return active OpenClaw sessions for the Synapse session drawer."""
    if HUB.gateway.is_connected:
        try:
            result = await HUB.gateway.request(
                "sessions.list", {"limit": 200, "activeMinutes": 120}
            )
            sessions = (result.get("payload") or {}).get("sessions", [])
            return {"ok": True, "sessions": _normalize_sessions(sessions)}
        except Exception as exc:
            return {"ok": False, "sessions": [], "error": str(exc)}
    gateway = openclaw_client.GatewayConnection()
    try:
        await gateway.connect()
        result = await gateway.request("sessions.list", {"limit": 200, "activeMinutes": 120})
        sessions = (result.get("payload") or {}).get("sessions", [])
        return {"ok": True, "sessions": _normalize_sessions(sessions)}
    except Exception as exc:
        return {"ok": False, "sessions": [], "error": str(exc)}
    finally:
        await gateway.close()


@router.get("/api/synapse/voice/sessions")
async def synapse_voice_sessions() -> dict[str, Any]:
    """Return active Ether-Voice bridge sessions."""
    return {"sessions": [session.to_api() for session in voice_bridge.list_sessions()]}


@router.post("/api/synapse/voice/sessions")
async def synapse_start_voice_session(request: Request) -> dict[str, Any]:
    """Attach Mission Control to Ether-Voice as a selected OpenClaw agent."""
    body = await request.json()
    try:
        session = await voice_bridge.start(
            str(body.get("agentId") or ""),
            str(body.get("sessionKey") or ""),
            str(body.get("paneId") or ""),
            str(body.get("model") or ""),
            str(body.get("clientId") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session": session.to_api()}


@router.delete("/api/synapse/voice/sessions/{session_id}")
async def synapse_stop_voice_session(session_id: str) -> dict[str, Any]:
    """Stop one active Ether-Voice bridge session."""
    session = await voice_bridge.stop(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Voice session not found")
    return {"session": session.to_api()}


@router.websocket("/api/synapse/ws")
async def synapse_ws(websocket: WebSocket) -> None:
    """Browser WebSocket — thin adapter onto the shared Synapse hub."""
    if not await _websocket_is_authorized(websocket):
        await websocket.close(code=1008)
        return
    cid = websocket.query_params.get("clientId") or uuid.uuid4().hex
    client_id = cid[:100]
    await HUB.handle_connect(client_id, websocket)
    try:
        while True:
            await HUB.handle_frame(client_id, await websocket.receive_json())
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        # Receiving on a socket that was closed/superseded mid-await raises
        # RuntimeError in Starlette — a normal close, not a failure.
        logger.info("synapse_ws: socket for %s closed: %s", client_id[:8], exc)
    except Exception:
        logger.exception("synapse_ws: connection loop failed for %s", client_id[:8])
    finally:
        HUB.handle_disconnect(client_id, websocket)


# ── REST-only helpers ─────────────────────────────────────────────────────────


async def _agent_statuses_from_gateway() -> list[dict[str, Any]]:
    gateway = openclaw_client.GatewayConnection()
    try:
        await gateway.connect(timeout=2)
        return await _agent_statuses(gateway)
    except Exception:
        return await _agent_statuses()
    finally:
        await gateway.close()


def _normalize_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    defaults = synapse_models.get_agent_model_defaults(openclaw_client.AGENT_REGISTRY.keys())
    rows = [_normalize_session(session, defaults) for session in sessions]
    return sorted(rows, key=lambda row: str(row.get("lastActive") or ""), reverse=True)


def _normalize_session(session: dict[str, Any], defaults: dict[str, str]) -> dict[str, Any]:
    session_key = str(session.get("key") or session.get("sessionKey") or "")
    agent_id = _agent_id_from_session_key(session_key) or str(session.get("agentId") or "unknown")
    explicit_model = _session_model_override(session)
    session_model = _session_model(session)
    context_max = _context_max(session, 200000)
    total_tokens = _estimated_context_used(session)
    last_active = session.get("updatedAt") or session.get("lastActive") or session.get("ts") or ""
    return {
        "sessionKey": session_key,
        "agentId": agent_id,
        "model": explicit_model or defaults.get(agent_id, "") or session_model,
        "defaultModel": defaults.get(agent_id, ""),
        "sessionModel": session_model,
        "lastActive": _session_timestamp(last_active),
        "totalTokens": int(total_tokens or 0),
        "contextTokens": int(context_max or 1),
    }


def _session_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        scale = 1000 if value > 10_000_000_000 else 1
        return datetime.fromtimestamp(value / scale, timezone.utc).isoformat()
    return str(value or "")


def _agent_id_from_session_key(session_key: str) -> str:
    if not session_key.startswith("agent:"):
        return ""
    parts = session_key.split(":")
    if len(parts) >= 2:
        return parts[1]
    return ""


async def _websocket_is_authorized(websocket: WebSocket) -> bool:
    if not auth_service.auth_is_enabled():
        return True
    token = websocket.cookies.get("session_token")
    return bool(await auth_service.verify_session_token(token))
