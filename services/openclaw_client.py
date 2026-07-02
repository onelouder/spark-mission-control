"""OpenClaw / Synapse gateway client.

A thin async wrapper around the WebSocket protocol Mission Control v1 spoke
to via ``GatewayClient`` in ``agent_router.py``. The shape here is
intentionally smaller: v2 only needs to *dispatch* a task and *subscribe*
to run-status updates — sub-agent spawning, capability probing, and the
v1 RPC mux all stay in v1 until they're proven necessary in v2.

Design notes:
    - The client is **env-gated**. If ``MOLTBOT_GATEWAY_WS_URL`` is unset
      or the WebSocket connection raises, dispatch returns an "offline"
      result rather than blowing up. This lets the API stay usable while
      the gateway is down and gives tests a deterministic offline path.
    - The dispatched message format ({"method": "agent.send", "params":
      {...}}) matches v1's protocol so existing Synapse instances need no
      changes.
    - The subscriber loop in :func:`subscribe_run_updates` is intended to
      live inside the FastAPI lifespan as a single ``asyncio.Task``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from config import get_settings

try:  # pragma: no cover — optional dep used only at runtime
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


GATEWAY_WS_URL_ENV = "MOLTBOT_GATEWAY_WS_URL"
GATEWAY_TOKEN_ENV = "MOLTBOT_TOKEN"
GATEWAY_INSECURE_TLS_ENV = "MOLTBOT_GATEWAY_INSECURE_TLS"
GATEWAY_ORIGIN_ENV = "MOLTBOT_GATEWAY_ORIGIN"
GATEWAY_CLIENT_ID_ENV = "MOLTBOT_GATEWAY_CLIENT_ID"
GATEWAY_CLIENT_MODE_ENV = "MOLTBOT_GATEWAY_CLIENT_MODE"
REQUESTED_GATEWAY_SCOPES = ["operator.read", "operator.write", "operator.admin"]


AGENT_REGISTRY: dict[str, dict[str, str]] = {
    "jarvis": {"name": "Jarvis", "session_key": "agent:jarvis:main", "org": "internal"},
    "atlas": {"name": "Atlas", "session_key": "agent:atlas:main", "org": "internal"},
    "aria": {"name": "Aria", "session_key": "agent:aria:main", "org": "internal"},
    "peter": {"name": "Peter", "session_key": "agent:peter:main", "org": "internal"},
    "watson": {"name": "Dr. Watson", "session_key": "agent:watson:main", "org": "internal"},
    "elon": {"name": "ELon", "session_key": "agent:elon:main", "org": "internal"},
    "elon-lite": {"name": "ELon (Lite)", "session_key": "agent:elon-lite:main", "org": "internal"},
    "dewey": {"name": "Dewey", "session_key": "agent:dewey:main", "org": "internal"},
    "ares": {"name": "Ares", "session_key": "agent:ares:main", "org": "internal"},
    "todd": {"name": "Todd", "session_key": "agent:todd:main", "org": "internal"},
    "donald": {"name": "Donald", "session_key": "agent:donald:main", "org": "internal"},
    "sterling": {"name": "Sterling", "session_key": "agent:sterling:main", "org": "internal"},
    "willb": {"name": "Will B.", "session_key": "agent:willb:main", "org": "venture"},
    "jc": {"name": "JC", "session_key": "agent:jc:main", "org": "venture"},
    "xavier": {"name": "Xavier", "session_key": "agent:xavier:main", "org": "xcognis"},
    "xena": {"name": "Xena", "session_key": "agent:xena:main", "org": "xcognis"},
    "xander": {"name": "Xander", "session_key": "agent:xander:main", "org": "xcognis"},
    "xyla": {"name": "Xyla", "session_key": "agent:xyla:main", "org": "xcognis"},
    "ximena": {"name": "Ximena", "session_key": "agent:ximena:main", "org": "xcognis"},
    "xerxes": {"name": "Xerxes", "session_key": "agent:xerxes:main", "org": "xcognis"},
    "xeno": {"name": "Xeno", "session_key": "agent:xeno:main", "org": "xcognis"},
}


@dataclass
class DispatchResult:
    """Outcome of a single ``send_to_agent`` call.

    Attributes:
        success: ``True`` when the gateway accepted the message.
        run_id: Synapse-issued run id; ``None`` for offline dispatches.
        offline: ``True`` when no gateway URL was configured or the
            connection failed; the caller can decide whether to retry
            later or treat the dispatch as queued.
        error: Human-readable failure detail (``None`` on success).
    """

    success: bool
    run_id: Optional[str] = None
    offline: bool = False
    error: Optional[str] = None


# Queue marker pushed by ``_listen`` when the socket dies so that
# ``next_event`` consumers fail fast instead of blocking forever.
_CLOSE_SENTINEL: dict = {}


class GatewayConnection:
    """Authenticated persistent connection to the OpenClaw gateway."""

    def __init__(self) -> None:
        self.ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._events: asyncio.Queue[dict] = asyncio.Queue()
        self._listen_task: Optional[asyncio.Task] = None
        self._closed = False

    async def connect(self, *, timeout: float = 5.0) -> None:
        url = gateway_url()
        if not url or websockets is None:
            raise RuntimeError("OpenClaw gateway is not configured")
        async with asyncio.timeout(timeout):
            self.ws = await websockets.connect(  # type: ignore[union-attr]
                url,
                ssl=_ssl_context() if url.startswith("wss://") else None,
                origin=gateway_origin(),
                max_size=2**21,
            )
            await _connect_gateway(self.ws)
        self._listen_task = asyncio.create_task(self._listen(), name="gateway-listener")

    async def close(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listen_task
        if self.ws is not None:
            await self.ws.close()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Gateway connection closed"))
        self._pending.clear()

    async def request(
        self, method: str, params: dict, *, timeout: float = 30.0
    ) -> dict:
        if self.ws is None:
            raise RuntimeError("Gateway connection is not open")
        request_id = uuid.uuid4().hex[:12]
        frame = {"type": "req", "id": request_id, "method": method, "params": params}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.ws.send(json.dumps(frame))
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)
        if not response.get("ok", True):
            raise RuntimeError(_gateway_error_message(response))
        return response

    async def next_event(self) -> dict:
        frame = await self._events.get()
        if frame is _CLOSE_SENTINEL:
            # Re-queue so any other waiter also wakes, then fail fast instead
            # of blocking forever on a dead connection.
            self._events.put_nowait(_CLOSE_SENTINEL)
            raise ConnectionError("Gateway connection closed")
        return frame

    async def _listen(self) -> None:
        exc: Exception = ConnectionError("Gateway connection closed")
        try:
            async for raw in self.ws:
                await self._handle_raw_frame(raw)
        except asyncio.CancelledError:
            raise
        except Exception as listen_exc:
            exc = listen_exc
        finally:
            # Runs on every exit path (normal close, error, cancellation):
            # fail in-flight RPCs and unblock event consumers.
            self._closed = True
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)
            self._events.put_nowait(_CLOSE_SENTINEL)

    async def _handle_raw_frame(self, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except ValueError:
            return
        if frame.get("type") == "res":
            fut = self._pending.get(frame.get("id"))
            if fut and not fut.done():
                fut.set_result(frame)
            return
        if frame.get("type") == "event":
            await self._events.put(frame)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def gateway_url() -> Optional[str]:
    """Return the configured Synapse WebSocket URL or ``None``."""
    env_value = os.environ.get(GATEWAY_WS_URL_ENV)
    if env_value is not None:
        return env_value or None
    return get_settings().moltbot_gateway_ws_url or None


def gateway_token() -> Optional[str]:
    """Return the bearer token used for the connect challenge."""
    env_value = os.environ.get(GATEWAY_TOKEN_ENV)
    if env_value:
        return env_value
    if get_settings().moltbot_token:
        return get_settings().moltbot_token
    return _read_gateway_token() or None


def _read_gateway_token() -> str:
    """Read the canonical OpenClaw gateway token when env is blank."""
    openclaw_home = Path(os.environ.get("OPENCLAW_HOME", "~/.openclaw")).expanduser()
    for name in ("openclaw.json", "moltbot.json"):
        try:
            cfg = json.loads((openclaw_home / name).read_text())
            token = cfg["gateway"]["auth"]["token"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if token:
            return str(token)
    return ""


def gateway_origin() -> Optional[str]:
    """Return the Origin header expected by the local gateway."""
    return os.environ.get(GATEWAY_ORIGIN_ENV) or "https://127.0.0.1:18789"


def _ssl_context() -> Optional[ssl.SSLContext]:
    """Build an SSL context that mirrors v1's self-signed-cert tolerance."""
    env_value = os.environ.get(GATEWAY_INSECURE_TLS_ENV)
    insecure = get_settings().moltbot_gateway_insecure_tls
    if env_value is not None:
        insecure = env_value not in ("0", "false", "False")
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def is_known_agent(agent_id: str) -> bool:
    """Cheap lookup used by the queue service to validate dispatch targets."""
    return agent_id in AGENT_REGISTRY


async def gateway_health(*, timeout: float = 3.0) -> dict[str, str]:
    """Probe Synapse reachability for the health endpoint.

    Returns a small dict with ``status`` in ``{disabled, ok, down}`` and an
    optional ``detail`` string. When ``MOLTBOT_GATEWAY_WS_URL`` is unset the
    gateway is intentionally offline and reports ``disabled`` — this does
    not imply a production outage.
    """
    url = gateway_url()
    if not url:
        return {"status": "disabled", "detail": "MOLTBOT_GATEWAY_WS_URL unset"}
    if websockets is None:
        return {"status": "down", "detail": "websockets package not installed"}

    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(  # type: ignore[union-attr]
                url,
                ssl=_ssl_context() if url.startswith("wss://") else None,
                origin=gateway_origin(),
            ):
                pass
        return {"status": "ok"}
    except (asyncio.TimeoutError, OSError, ValueError) as exc:
        logger.debug("openclaw_client: gateway health probe failed: %s", exc)
        return {"status": "down", "detail": str(exc)}


async def send_to_agent(
    agent_id: str, prompt: str, *, timeout: float = 5.0
) -> DispatchResult:
    """Send a single task prompt to the named agent.

    Returns an :class:`DispatchResult` rather than raising. Callers should
    branch on ``result.offline`` vs ``result.success`` to decide whether
    to retry the dispatch later.

    Args:
        agent_id: Key in :data:`AGENT_REGISTRY`.
        prompt: Fully-rendered task prompt.
        timeout: Hard deadline in seconds for the connect+send round-trip.
    """
    if agent_id not in AGENT_REGISTRY:
        return DispatchResult(success=False, error=f"unknown agent: {agent_id}")

    url = gateway_url()
    if not url or websockets is None:
        logger.info(
            "openclaw_client: dispatch for %s queued offline "
            "(MOLTBOT_GATEWAY_WS_URL=%s, websockets=%s)",
            agent_id,
            bool(url),
            websockets is not None,
        )
        return DispatchResult(success=True, offline=True, run_id=None)

    session_key = AGENT_REGISTRY[agent_id]["session_key"]
    request_id = uuid.uuid4().hex[:12]
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(  # type: ignore[union-attr]
                url,
                ssl=_ssl_context() if url.startswith("wss://") else None,
                origin=gateway_origin(),
            ) as ws:
                await _connect_gateway(ws)
                response = await _request_gateway(
                    ws,
                    request_id=request_id,
                    method="chat.send",
                    params={
                        "sessionKey": session_key,
                        "message": prompt,
                        "idempotencyKey": request_id,
                    },
                )
    except (asyncio.TimeoutError, OSError) as exc:
        logger.warning("openclaw_client: dispatch queued offline for %s: %s", agent_id, exc)
        return DispatchResult(success=True, offline=True, error=str(exc))
    except (ValueError, RuntimeError) as exc:
        logger.warning("openclaw_client: dispatch failed for %s: %s", agent_id, exc)
        return DispatchResult(success=False, error=str(exc))

    payload = response.get("payload") or {}
    run_id = payload.get("runId") or response.get("runId")
    if response.get("ok") and run_id:
        logger.info(
            "openclaw_client: dispatched %s → %s (run_id=%s)", agent_id, session_key, run_id
        )
        return DispatchResult(success=True, run_id=run_id)
    return DispatchResult(
        success=False,
        error=str(response.get("error") or "missing runId in response"),
    )


async def subscribe_run_updates() -> AsyncIterator[dict]:
    """Yield Synapse ``run.status`` events for the lifespan subscriber.

    The function is a thin async generator so the lifespan task can wrap
    it in a ``try / except CancelledError`` and call its consumer with
    each event. When no gateway URL is configured, the generator yields
    nothing and returns immediately.
    """
    url = gateway_url()
    if not url or websockets is None:
        logger.info(
            "openclaw_client: run-update subscriber inactive "
            "(MOLTBOT_GATEWAY_WS_URL=%s, websockets=%s)",
            bool(url),
            websockets is not None,
        )
        return

    try:
        async with websockets.connect(  # type: ignore[union-attr]
            url,
            ssl=_ssl_context() if url.startswith("wss://") else None,
            origin=gateway_origin(),
        ) as ws:
            await _connect_gateway(ws)
            while True:
                raw = await ws.recv()
                with suppress(ValueError):
                    event = _run_status_event(json.loads(raw))
                    if event is not None:
                        yield event
    except (asyncio.CancelledError, OSError, RuntimeError) as exc:  # pragma: no cover
        logger.info("openclaw_client: subscriber exiting: %s", exc)
        raise


async def _connect_gateway(ws) -> None:
    """Complete the v1 OpenClaw gateway connect handshake."""
    with suppress(asyncio.TimeoutError, ValueError):
        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
        json.loads(raw)

    connect_frame = {
        "type": "req",
        "id": uuid.uuid4().hex[:12],
        "method": "connect",
        "params": {
            "minProtocol": 4,
            "maxProtocol": 4,
            "client": {
                "id": os.environ.get(GATEWAY_CLIENT_ID_ENV, "openclaw-control-ui"),
                "displayName": "Mission Control v2",
                "version": "2.0.0",
                "platform": "linux",
                "mode": os.environ.get(GATEWAY_CLIENT_MODE_ENV, "ui"),
            },
            "auth": {"token": gateway_token() or ""},
            "role": "operator",
            "scopes": REQUESTED_GATEWAY_SCOPES,
        },
    }
    response = await _request_gateway_frame(ws, connect_frame, timeout=5.0)
    if not response.get("ok"):
        raise RuntimeError(_gateway_error_message(response))


async def _request_gateway(
    ws,
    *,
    request_id: str,
    method: str,
    params: dict,
    timeout: float = 30.0,
) -> dict:
    frame = {"type": "req", "id": request_id, "method": method, "params": params}
    response = await _request_gateway_frame(ws, frame, timeout=timeout)
    if not response.get("ok", True):
        raise RuntimeError(_gateway_error_message(response))
    return response


async def _request_gateway_frame(ws, frame: dict, *, timeout: float) -> dict:
    await ws.send(json.dumps(frame))
    async with asyncio.timeout(timeout):
        while True:
            raw = await ws.recv()
            response = json.loads(raw)
            if response.get("type") == "res" and response.get("id") == frame["id"]:
                return response


def _gateway_error_message(response: dict) -> str:
    error = response.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "gateway request failed")
    return str(error or "gateway request failed")


def _run_status_event(frame: dict) -> Optional[dict]:
    if frame.get("type") != "event":
        return None
    if frame.get("event") == "chat":
        return _chat_run_status(frame.get("payload") or {})
    if frame.get("event") == "agent":
        return _agent_run_status(frame.get("payload") or {})
    return None


def _chat_run_status(payload: dict) -> Optional[dict]:
    run_id = payload.get("runId")
    state = payload.get("state")
    status = {
        "started": "running",
        "final": "completed",
        "aborted": "failed",
        "error": "failed",
    }.get(state)
    if not run_id or not status:
        return None
    return {
        "topic": "run.status",
        "payload": {
            "runId": run_id,
            "status": status,
            "error": payload.get("errorMessage") or payload.get("summary"),
        },
    }


def _agent_run_status(payload: dict) -> Optional[dict]:
    run_id = payload.get("runId")
    status = payload.get("status")
    if not run_id or not status:
        return None
    return {"topic": "run.status", "payload": {"runId": run_id, "status": status}}


def extract_message_text(content, *, depth: int = 0) -> str:
    """Extract human-readable text from OpenClaw message content."""
    if content is None or depth > 6:
        return ""
    if isinstance(content, str):
        return _extract_from_string(content, depth)
    if isinstance(content, list):
        parts = [extract_message_text(item, depth=depth + 1) for item in content]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        block_type = content.get("type", "")
        if block_type in {"toolCall", "toolResult", "thinking"}:
            return ""
        for key in ("text", "delta", "content", "message", "output"):
            text = extract_message_text(content.get(key), depth=depth + 1)
            if text:
                return text
    return ""


def _extract_from_string(value: str, depth: int) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped[0] in "{[":
        with suppress(ValueError):
            text = extract_message_text(json.loads(stripped), depth=depth + 1)
            if text:
                return text
    if stripped == "NO_REPLY" or "heartbeat_ok" in stripped.lower():
        return ""
    return value
