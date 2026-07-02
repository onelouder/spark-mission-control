"""Shared Synapse hub — one multiplexed OpenClaw gateway connection.

Replaces the per-browser-tab ``SynapseBridge`` model: a single supervised
gateway socket (``SharedGateway``) feeds a fan-out layer
(``ConnectionManager``) that routes chat/status frames to every subscribed
browser client. Ported from Mission Control v1's ``AgentRouter`` /
``ConnectionManager`` (agent_router.py) with two efficiency upgrades:

    - Per-client bounded send queues with a dedicated sender task, so the
      single gateway reader never blocks on a slow browser socket. Under
      pressure, streaming ``chunk`` frames coalesce losslessly and stale
      ``status`` snapshots are replaced; control frames are never dropped.
    - The gateway supervisor reconnects with exponential backoff and, on
      recovery, replays history to subscribed panes so replies that landed
      during an outage appear without a page reload.

Design constraints (mirrors ``dispatch_subscriber``):
    - Env-gated: ``HUB.start()`` is a no-op when ``MOLTBOT_GATEWAY_WS_URL``
      is unset, keeping the offline test suite inert.
    - No silent failures: every background task logs on error.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter, deque
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from services import openclaw_client, synapse_models

logger = logging.getLogger(__name__)

RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
# Push events (chat/agent) carry state transitions in real time; the poll is
# a slow consistency sweep, and its sessions.list result is cached and shared
# with handle_connect and the REST fleet endpoint.
STATUS_POLL_INTERVAL = 10.0
SESSIONS_CACHE_TTL = 4.0
RUN_ORPHAN_TIMEOUT = 900.0
RUN_HEARTBEAT_INITIAL_SECONDS = 45.0
RUN_HEARTBEAT_INTERVAL_SECONDS = 30.0
CLIENT_QUEUE_MAXSIZE = 256
HISTORY_LIMIT = 100
# Reconnect-storm guard: a healthy tab reconnects a handful of times a minute
# at worst (backoff floor 500ms applies only after repeated failures).
CONNECT_RATE_LIMIT = 20
CONNECT_RATE_WINDOW = 60.0

# Lightweight operational counters, exposed via /api/synapse/hub/stats.
STATS: Counter = Counter()


# ── Frame/agent helpers (shared with api.routers.synapse) ────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(value: Any) -> str:
    raw = str(value or "idle").lower()
    if raw in {"active", "running", "started", "working", "processing", "busy"}:
        return "working"
    if raw in {"blocked", "waiting", "queued"}:
        return "blocked"
    if raw in {"error", "failed"}:
        return "error"
    return "idle"


def _session_key(agent_id: str) -> str:
    return openclaw_client.AGENT_REGISTRY[agent_id]["session_key"]


def _session_key_matches_agent(agent_id: str, session_key: str) -> bool:
    parts = session_key.strip().split(":")
    return len(parts) >= 2 and parts[0] == "agent" and parts[1] == agent_id


def _agent_id_from_payload(payload: dict[str, Any]) -> Optional[str]:
    session_key = payload.get("sessionKey") or ""
    if session_key.startswith("agent:"):
        parts = session_key.split(":")
        if len(parts) >= 2 and parts[1] in openclaw_client.AGENT_REGISTRY:
            return parts[1]
    for agent_id, info in openclaw_client.AGENT_REGISTRY.items():
        if info["session_key"] == session_key:
            return agent_id
    return None


# Exact session-key → agent map. Chat *content* relays only for an agent's
# main session: cron jobs (agent:<id>:cron:<job>:run:<run>) and voice
# sessions share the agent prefix and must not flood the chat panes.
_AGENT_BY_SESSION_KEY: dict[str, str] = {
    info["session_key"]: agent_id
    for agent_id, info in openclaw_client.AGENT_REGISTRY.items()
}


def _chat_agent_id(payload: dict[str, Any]) -> Optional[str]:
    return _AGENT_BY_SESSION_KEY.get(payload.get("sessionKey") or "")


def _event_text(payload: dict[str, Any]) -> str:
    for key in ("delta", "message", "text", "content"):
        text = openclaw_client.extract_message_text(payload.get(key))
        if text:
            return text
    return ""


def _history_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = openclaw_client.extract_message_text(message.get("content", message.get("text")))
        if text:
            rows.append({"role": role, "text": text, "ts": message.get("ts") or _now()})
    return rows


def _base_agent(agent_id: str, model_defaults: Optional[dict[str, str]] = None) -> dict[str, Any]:
    info = openclaw_client.AGENT_REGISTRY[agent_id]
    default_model = (model_defaults or {}).get(agent_id, "")
    return {
        "agentId": agent_id,
        "id": agent_id,
        "name": info["name"],
        "state": "idle",
        "task": None,
        "contextPct": 0,
        "contextUsed": 0,
        "contextMax": _model_context_window(default_model) or 200000,
        "model": default_model,
        "defaultModel": default_model,
        "sessionModel": "",
        "lastActivity": _now(),
        "sessionKey": info["session_key"],
        "org": info.get("org", "internal"),
    }


def _session_model_override(session: dict[str, Any], fallback: str = "") -> str:
    raw_model = session.get("modelOverride") or ""
    model = str(raw_model or "").strip()
    provider = str(session.get("providerOverride") or "").strip()
    if provider and model and "/" not in model:
        return f"{provider}/{model}"
    return model or fallback


def _session_model(session: dict[str, Any], fallback: str = "") -> str:
    raw_model = session.get("modelOverride") or session.get("model") or ""
    model = str(raw_model or "").strip()
    provider = str(session.get("providerOverride") or session.get("modelProvider") or "").strip()
    if provider and model and "/" not in model:
        return f"{provider}/{model}"
    return model or fallback


def _context_max(session: dict[str, Any], default: int) -> int:
    return int(session.get("contextMax") or session.get("contextWindow") or session.get("contextTokens") or default)


def _context_used(session: dict[str, Any]) -> int:
    usage = session.get("usage") if isinstance(session.get("usage"), dict) else {}
    total = (
        session.get("contextUsed")
        or session.get("usedTokens")
        or session.get("totalTokens")
        or usage.get("totalTokens")
        or usage.get("total_tokens")
        or 0
    )
    return int(total or 0)


def _estimated_context_used(session: dict[str, Any]) -> int:
    used = _context_used(session)
    if used > 0 or session.get("totalTokensFresh") is True:
        return used
    session_file = str(session.get("sessionFile") or "")
    if not session_file:
        return 0
    try:
        return max(0, Path(session_file).stat().st_size // 4)
    except OSError:
        return 0


def _has_context_data(session: dict[str, Any]) -> bool:
    usage = session.get("usage")
    return any(
        session.get(key) is not None
        for key in ("contextUsed", "usedTokens", "totalTokens", "contextPct")
    ) or isinstance(usage, dict)


def _context_pct(session: dict[str, Any], context_used: int, context_max: int) -> float:
    if context_max:
        return round(float(context_used) / context_max * 100, 2)
    if session.get("contextPct") is not None:
        return float(session["contextPct"])
    return 0


def _model_context_window(model: str) -> int:
    """Configured context window for a model id/alias (0 = unknown)."""
    if not model:
        return 0
    return synapse_models.get_model_catalog().context_window_for(model)


def _merge_session(row: dict[str, Any], session: dict[str, Any]) -> None:
    row["state"] = _state(session.get("status") or session.get("state") or row["state"])
    row["task"] = session.get("task") or row["task"]
    session_model = _session_model(session)
    explicit_model = _session_model_override(session)
    row["sessionModel"] = session_model
    if explicit_model or not row["model"]:
        row["model"] = explicit_model or session_model
    model_context = _model_context_window(row["model"]) or _model_context_window(session_model)
    row["contextMax"] = model_context or _context_max(session, row["contextMax"])
    row["contextUsed"] = _estimated_context_used(session)
    row["contextPct"] = _context_pct(session, row["contextUsed"], row["contextMax"])


def _merge_sessions(rows: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {row["sessionKey"]: row for row in rows}
    for session in sessions:
        row = by_key.get(session.get("key") or session.get("sessionKey"))
        if row is None:
            continue
        _merge_session(row, session)
    return rows


def _patched_model(response: dict[str, Any], fallback: str) -> str:
    payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
    resolved = payload.get("resolved") if isinstance(payload.get("resolved"), dict) else {}
    return _session_model(resolved, _session_model(payload, fallback))


def _message_model(agent_id: str, payload: dict[str, Any]) -> str:
    catalog = synapse_models.get_model_catalog()
    requested = str(payload.get("model") or payload.get("modelOverride") or "").strip()
    if requested:
        return catalog.resolve(requested)
    defaults = synapse_models.get_agent_model_defaults((agent_id,))
    return catalog.resolve(defaults.get(agent_id, ""))


async def _agent_statuses(gateway: Optional[Any] = None) -> list[dict[str, Any]]:
    """Build agent rows, enriched from ``sessions.list`` when a gateway is up.

    ``gateway`` is duck-typed: anything with an async ``request(method,
    params, timeout=...)`` works (``GatewayConnection`` or ``SharedGateway``).
    """
    defaults = synapse_models.get_agent_model_defaults(openclaw_client.AGENT_REGISTRY.keys())
    rows = [_base_agent(agent_id, defaults) for agent_id in openclaw_client.AGENT_REGISTRY]
    if gateway is None:
        return rows
    try:
        result = await gateway.request(
            "sessions.list",
            {"limit": 200, "activeMinutes": 240, "configuredAgentsOnly": True},
            timeout=5,
        )
    except Exception:
        return rows
    return _merge_sessions(rows, (result.get("payload") or {}).get("sessions", []))


async def _set_agent_model(
    agent_id: str,
    model: str,
    *,
    gateway: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply a session-scoped model override via ``sessions.patch``."""
    if agent_id not in openclaw_client.AGENT_REGISTRY:
        return {"ok": False, "error": "Unknown agent"}
    catalog = synapse_models.get_model_catalog()
    resolved = catalog.resolve(model)
    valid_ids = {entry.id for entry in catalog.models}
    if not resolved:
        return {"ok": False, "error": "Model required"}
    if valid_ids and resolved not in valid_ids:
        return {"ok": False, "error": f"Invalid model: {model}"}

    own_gateway = gateway is None
    active_gateway = gateway or openclaw_client.GatewayConnection()
    try:
        if own_gateway:
            await active_gateway.connect()
        response = await active_gateway.request(
            "sessions.patch", {"key": _session_key(agent_id), "model": resolved}
        )
        model = _patched_model(response, resolved)
        return {"ok": True, "agent": agent_id, "model": model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if own_gateway:
            await active_gateway.close()


# ── Browser fan-out ───────────────────────────────────────────────────────────


class _ClientChannel:
    """Outbound pipe for one browser client: bounded queue + sender task.

    ``offer`` never blocks the caller (the shared gateway reader). Under
    backpressure: ``chunk`` frames for the same (agent, run) coalesce by
    appending text (lossless), ``status``/``status_all`` snapshots are
    replaced latest-wins, and control frames are never dropped — a client
    whose queue fills with control frames is force-closed so its frontend
    reconnects and re-syncs from history.
    """

    def __init__(self, client_id: str, websocket: Any) -> None:
        self.client_id = client_id
        self.websocket = websocket
        self.closed = False
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAXSIZE)
        # Frames still sitting in the queue, addressable for coalescing.
        # Refs are cleared synchronously by the sender before any await, so a
        # tracked frame is guaranteed not to have been serialized yet.
        self._queued_chunks: dict[tuple, dict] = {}
        self._queued_status: dict[str, dict] = {}
        self.sender_task = asyncio.create_task(
            self._drain(), name=f"synapse-client-{client_id[:8]}"
        )

    def offer(self, frame: dict) -> None:
        if self.closed:
            return
        frame_type = frame.get("type")
        if frame_type == "chunk":
            self._offer_chunk(frame)
        elif frame_type in ("status", "status_all"):
            self._offer_status(frame)
        else:
            self._offer_control(frame)

    def _offer_chunk(self, frame: dict) -> None:
        key = (frame.get("agentId"), (frame.get("payload") or {}).get("runId"))
        queued = self._queued_chunks.get(key)
        if queued is not None:
            queued["payload"]["text"] += frame["payload"]["text"]
            queued["ts"] = frame.get("ts")
            return
        # Private copy: the same frame dict is offered to multiple clients and
        # coalescing mutates it, so each queue needs its own payload.
        copy = {**frame, "payload": dict(frame.get("payload") or {})}
        try:
            self.queue.put_nowait(copy)
            self._queued_chunks[key] = copy
        except asyncio.QueueFull:
            # Rare: queue full of control frames. The terminal message (or the
            # accumulated run text) restores the full reply, so a lost delta
            # self-heals.
            STATS["client_chunk_drops"] += 1
            logger.debug("synapse_hub: dropped chunk for slow client %s", self.client_id[:8])

    def _offer_status(self, frame: dict) -> None:
        key = str(frame.get("agentId") or "__all__")
        queued = self._queued_status.get(key)
        if queued is not None:
            queued["payload"] = frame.get("payload")
            queued["ts"] = frame.get("ts")
            return
        copy = dict(frame)
        try:
            self.queue.put_nowait(copy)
            self._queued_status[key] = copy
        except asyncio.QueueFull:
            pass  # stale snapshot; the next poll re-broadcasts

    def _offer_control(self, frame: dict) -> None:
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            STATS["client_forced_closes"] += 1
            logger.warning(
                "synapse_hub: client %s send queue wedged; closing socket",
                self.client_id[:8],
            )
            self.shutdown()

    async def _drain(self) -> None:
        try:
            while True:
                frame = await self.queue.get()
                # Clear coalesce refs before the await so later offers for the
                # same key enqueue a fresh frame instead of mutating this one
                # mid-serialization.
                self._untrack(frame)
                await self.websocket.send_json(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("synapse_hub: sender for %s stopped: %s", self.client_id[:8], exc)
            self.closed = True

    def _untrack(self, frame: dict) -> None:
        frame_type = frame.get("type")
        if frame_type == "chunk":
            key = (frame.get("agentId"), (frame.get("payload") or {}).get("runId"))
            if self._queued_chunks.get(key) is frame:
                del self._queued_chunks[key]
        elif frame_type in ("status", "status_all"):
            key = str(frame.get("agentId") or "__all__")
            if self._queued_status.get(key) is frame:
                del self._queued_status[key]

    def shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.sender_task.cancel()

        async def _close() -> None:
            with suppress(Exception):
                await self.websocket.close()

        asyncio.create_task(_close())


class ConnectionManager:
    """Tracks browser clients and their per-agent subscriptions."""

    def __init__(self) -> None:
        self.channels: dict[str, _ClientChannel] = {}
        self.subscriptions: dict[str, set[str]] = {}

    async def connect(self, client_id: str, websocket: Any) -> None:
        await websocket.accept()
        STATS["client_connects"] += 1
        prev = self.channels.get(client_id)
        if prev is not None:
            # Same tab reconnected before the old socket's cleanup ran.
            STATS["client_evictions"] += 1
            prev.shutdown()
        self.channels[client_id] = _ClientChannel(client_id, websocket)
        # Preserve subscriptions across reconnects (stable client_id) so an
        # in-flight run's reply still routes to the reconnected socket.
        self.subscriptions.setdefault(client_id, set())
        logger.info(
            "synapse_hub: client %s connected (total %d)", client_id[:8], len(self.channels)
        )

    def disconnect(self, client_id: str, websocket: Any = None) -> None:
        chan = self.channels.get(client_id)
        if chan is None:
            return
        # Reconnect race guard: a stale socket's cleanup must not evict the
        # fresh socket registered under the same client_id.
        if websocket is not None and chan.websocket is not websocket:
            return
        chan.shutdown()
        del self.channels[client_id]
        self.subscriptions.pop(client_id, None)
        logger.info(
            "synapse_hub: client %s disconnected (total %d)", client_id[:8], len(self.channels)
        )

    def subscribe(self, client_id: str, agent_id: str) -> None:
        self.subscriptions.setdefault(client_id, set()).add(agent_id)

    def get_subscribers_for_agent(self, agent_id: str) -> list[str]:
        return [
            client_id
            for client_id, agents in self.subscriptions.items()
            if agent_id in agents and client_id in self.channels
        ]

    def send_to_client(self, client_id: str, frame: dict) -> None:
        chan = self.channels.get(client_id)
        if chan is not None:
            chan.offer(frame)

    def broadcast(self, frame: dict) -> None:
        for chan in list(self.channels.values()):
            chan.offer(frame)

    def shutdown_all(self) -> None:
        for chan in list(self.channels.values()):
            chan.shutdown()
        self.channels.clear()
        self.subscriptions.clear()


# ── Shared gateway connection ────────────────────────────────────────────────


class SharedGateway:
    """Supervises one persistent gateway connection shared by all clients."""

    def __init__(self) -> None:
        self.conn: Optional[openclaw_client.GatewayConnection] = None
        self._event_handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        self._status_handlers: list[Callable[[dict], Awaitable[None]]] = []
        self._supervisor_task: Optional[asyncio.Task] = None
        self._running = False
        self._connected = asyncio.Event()
        self._last_status: Optional[bool] = None

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def on_event(self, event_name: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._event_handlers.setdefault(event_name, []).append(handler)

    def on_status_change(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._status_handlers.append(handler)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name="synapse-hub-gateway"
        )

    async def stop(self) -> None:
        self._running = False
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._supervisor_task
            self._supervisor_task = None

    async def request(self, method: str, params: dict, *, timeout: float = 30.0) -> dict:
        conn = self.conn
        if conn is None:
            raise RuntimeError("OpenClaw gateway is unavailable")
        started = time.monotonic()
        try:
            return await conn.request(method, params, timeout=timeout)
        finally:
            STATS["gateway_requests"] += 1
            STATS["gateway_request_ms_total"] += int((time.monotonic() - started) * 1000)

    async def _supervise(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while self._running:
            conn = openclaw_client.GatewayConnection()
            try:
                await conn.connect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "synapse_hub: gateway connect failed: %s (retry in %.0fs)", exc, delay
                )
                await self._emit_status(False, str(exc))
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue

            self.conn = conn
            self._connected.set()
            delay = RECONNECT_INITIAL_DELAY
            STATS["gateway_connects"] += 1
            logger.info("synapse_hub: gateway connected")
            await self._emit_status(True, None)
            try:
                while True:
                    frame = await conn.next_event()
                    await self._dispatch_event(frame)
            except asyncio.CancelledError:
                raise
            except ConnectionError as exc:
                logger.warning("synapse_hub: gateway connection lost: %s", exc)
                await self._emit_status(False, str(exc))
            except Exception:
                logger.exception("synapse_hub: gateway reader failed; reconnecting")
                await self._emit_status(False, "reader failure")
            finally:
                self._connected.clear()
                self.conn = None
                with suppress(Exception):
                    await conn.close()

    async def _dispatch_event(self, frame: dict) -> None:
        for handler in self._event_handlers.get(frame.get("event"), []):
            try:
                await handler(frame)
            except Exception:
                logger.exception(
                    "synapse_hub: %s event handler failed", frame.get("event")
                )

    async def _emit_status(self, connected: bool, detail: Optional[str]) -> None:
        if connected == self._last_status:
            return
        self._last_status = connected
        snapshot: dict[str, Any] = {"connected": connected}
        if detail:
            snapshot["detail"] = detail
        for handler in self._status_handlers:
            try:
                await handler(snapshot)
            except Exception:
                logger.exception("synapse_hub: status handler failed")


# ── The hub ───────────────────────────────────────────────────────────────────


class SynapseHub:
    """Routes frames between browser clients and the shared gateway."""

    def __init__(self) -> None:
        self.manager = ConnectionManager()
        self.gateway = SharedGateway()
        self.gateway.on_event("chat", self._handle_chat_event)
        self.gateway.on_event("agent", self._handle_agent_event)
        self.gateway.on_status_change(self._on_gateway_status)
        # runId -> {agent_id, client_id, client_message_id, acc_text, started_at}
        self._active_runs: dict[str, dict] = {}
        # Last assistant text delivered per agent — guards terminal replays
        # (gateway reconnect) and the history fallback against duplicates.
        self._last_delivered_text: dict[str, str] = {}
        self._voice_waiters: dict[str, asyncio.Future] = {}
        self._status_task: Optional[asyncio.Task] = None
        self._running = False
        self._background_tasks: set[asyncio.Task] = set()
        # Shared sessions.list snapshot: one gateway call serves the status
        # poll, every connecting client, and the REST fleet endpoint.
        self._sessions_cache: Optional[list[dict]] = None
        self._sessions_cache_at = 0.0
        self._sessions_lock = asyncio.Lock()
        self._selected_models: dict[str, str] = {}
        # clientId -> recent connect timestamps (reconnect-storm guard).
        self._connect_history: dict[str, deque] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        if not openclaw_client.gateway_url():
            logger.info(
                "synapse_hub: no %s set; hub idle", openclaw_client.GATEWAY_WS_URL_ENV
            )
            return
        self._running = True
        await self.gateway.start()
        self._status_task = asyncio.create_task(
            self._status_poll_loop(), name="synapse-hub-status"
        )
        logger.info("synapse_hub: started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._status_task is not None:
            self._status_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._status_task
            self._status_task = None
        for task in list(self._background_tasks):
            task.cancel()
        await self.gateway.stop()
        self.manager.shutdown_all()
        logger.info("synapse_hub: stopped")

    def _spawn(self, coro: Awaitable[None], label: str) -> None:
        task = asyncio.create_task(coro, name=f"synapse-hub-{label}")
        self._background_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._background_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error(
                    "synapse_hub: background task %s failed", label, exc_info=t.exception()
                )

        task.add_done_callback(_done)

    # ── Shared sessions snapshot ─────────────────────────────────────────────

    async def _cached_sessions(self) -> Optional[list[dict]]:
        """sessions.list with a short TTL + single-flight; None when offline."""
        if not self.gateway.is_connected:
            return None
        now = time.monotonic()
        if self._sessions_cache is not None and now - self._sessions_cache_at < SESSIONS_CACHE_TTL:
            STATS["sessions_list_cache_hits"] += 1
            return self._sessions_cache
        async with self._sessions_lock:
            now = time.monotonic()
            if self._sessions_cache is not None and now - self._sessions_cache_at < SESSIONS_CACHE_TTL:
                STATS["sessions_list_cache_hits"] += 1
                return self._sessions_cache
            try:
                result = await self.gateway.request(
                    "sessions.list",
                    {"limit": 200, "activeMinutes": 240, "configuredAgentsOnly": True},
                    timeout=5,
                )
            except Exception as exc:
                logger.warning("synapse_hub: sessions.list failed: %s", exc)
                return None
            STATS["sessions_list_calls"] += 1
            self._sessions_cache = (result.get("payload") or {}).get("sessions", [])
            self._sessions_cache_at = time.monotonic()
            return self._sessions_cache

    async def agent_statuses(self) -> list[dict[str, Any]]:
        """Agent rows enriched from the shared (cached) sessions snapshot."""
        defaults = synapse_models.get_agent_model_defaults(openclaw_client.AGENT_REGISTRY.keys())
        rows = [_base_agent(agent_id, defaults) for agent_id in openclaw_client.AGENT_REGISTRY]
        sessions = await self._cached_sessions()
        if sessions:
            _merge_sessions(rows, sessions)
        return rows

    # ── Browser client lifecycle (called by the WS endpoint) ────────────────

    def _connect_rate_exceeded(self, client_id: str) -> bool:
        now = time.monotonic()
        history = self._connect_history.setdefault(client_id, deque())
        while history and now - history[0] > CONNECT_RATE_WINDOW:
            history.popleft()
        history.append(now)
        # Opportunistic cleanup so departed clients don't accumulate.
        if len(self._connect_history) > 512:
            for key in [k for k, v in self._connect_history.items() if not v]:
                del self._connect_history[key]
        return len(history) > CONNECT_RATE_LIMIT

    async def handle_connect(self, client_id: str, websocket: Any) -> None:
        if self._connect_rate_exceeded(client_id):
            STATS["rate_limited_connects"] += 1
            if STATS["rate_limited_connects"] % 50 == 1:  # log storms once, not per attempt
                logger.warning(
                    "synapse_hub: connect rate limit hit for client %s (>%d/%ds)",
                    client_id[:8],
                    CONNECT_RATE_LIMIT,
                    int(CONNECT_RATE_WINDOW),
                )
            with suppress(Exception):
                await websocket.close(code=1013)  # try again later
            return
        await self.manager.connect(client_id, websocket)
        agents = await self.agent_statuses()
        self.manager.send_to_client(
            client_id,
            {
                "type": "connected",
                "clientId": client_id,
                "ts": _now(),
                "payload": {
                    "agents": agents,
                    "gateway": {"connected": self.gateway.is_connected},
                },
            },
        )

    def handle_disconnect(self, client_id: str, websocket: Any = None) -> None:
        self.manager.disconnect(client_id, websocket)

    async def handle_frame(self, client_id: str, frame: dict) -> None:
        try:
            await self._dispatch_client_frame(client_id, frame)
        except Exception:
            logger.exception(
                "synapse_hub: frame %s from %s failed", frame.get("type"), client_id[:8]
            )
            self._send_error(
                client_id,
                f"Internal error handling {frame.get('type')}",
                frame.get("agentId"),
            )

    async def _dispatch_client_frame(self, client_id: str, frame: dict) -> None:
        frame_type = frame.get("type")
        agent_id = frame.get("agentId")
        payload = frame.get("payload") or {}
        if frame_type == "subscribe" and agent_id:
            self.manager.subscribe(client_id, agent_id)
            await self._send_history(client_id, agent_id, HISTORY_LIMIT, frame_type="subscribed")
        elif frame_type == "message" and agent_id:
            await self._handle_message(client_id, agent_id, payload)
        elif frame_type == "history" and agent_id:
            await self._send_history(client_id, agent_id, int(payload.get("limit") or HISTORY_LIMIT))
        elif frame_type == "abort" and agent_id:
            await self._handle_abort(client_id, agent_id)
        elif frame_type == "reset" and agent_id:
            await self._handle_reset(client_id, agent_id)
        elif frame_type == "set_model" and agent_id:
            await self._handle_set_model(client_id, agent_id, payload)
        elif frame_type == "ping":
            self.manager.send_to_client(client_id, {"type": "pong", "ts": _now()})
        else:
            self._send_error(client_id, f"Unknown frame type: {frame_type}", agent_id)

    async def _handle_message(self, client_id: str, agent_id: str, payload: dict) -> None:
        text = str(payload.get("text") or "").strip()
        if not text:
            self._send_error(client_id, "Empty message", agent_id)
            return
        client_message_id = str(payload.get("clientMessageId") or uuid.uuid4())
        try:
            await self._ensure_agent_model(agent_id, _message_model(agent_id, payload))
        except Exception as exc:
            logger.warning("synapse_hub: model patch failed for %s: %s", agent_id, exc)
            self._send_error(client_id, str(exc), agent_id)
            return
        try:
            result = await self.gateway.request(
                "chat.send",
                {
                    "sessionKey": _session_key(agent_id),
                    "message": text,
                    "idempotencyKey": client_message_id,
                },
            )
        except Exception as exc:
            logger.warning("synapse_hub: chat.send failed for %s: %s", agent_id, exc)
            self._send_error(client_id, str(exc), agent_id)
            return
        send_payload = result.get("payload") or {}
        run_id = str(send_payload.get("runId") or "")
        if run_id:
            self._active_runs[run_id] = {
                "agent_id": agent_id,
                "client_id": client_id,
                "client_message_id": client_message_id,
                "acc_text": "",
                "started_at": time.monotonic(),
                "last_output_at": time.monotonic(),
            }
        self.manager.send_to_client(
            client_id,
            {
                "type": "ack",
                "agentId": agent_id,
                "ts": _now(),
                "payload": {
                    "sent": True,
                    "runId": run_id,
                    "clientMessageId": client_message_id,
                    "text": text,
                    "status": send_payload.get("status") or "accepted",
                },
            },
        )

    async def send_voice_message(
        self,
        client_id: str,
        pane_id: str,
        agent_id: str,
        session_key: str,
        text: str,
        client_message_id: str,
        model: str = "",
    ) -> tuple[str, asyncio.Future]:
        if not client_id:
            raise RuntimeError("voice session is not bound to a Synapse client")
        if not pane_id:
            raise RuntimeError("voice session is not bound to a Synapse pane")
        if not _session_key_matches_agent(agent_id, session_key):
            raise RuntimeError("voice sessionKey does not match agentId")
        if client_id not in self.manager.channels:
            raise RuntimeError("Synapse client is not connected")
        self.manager.subscribe(client_id, agent_id)
        self.manager.send_to_client(
            client_id,
            {
                "type": "voice_user",
                "agentId": agent_id,
                "paneId": pane_id,
                "ts": _now(),
                "payload": {"text": text, "clientMessageId": client_message_id, "paneId": pane_id},
            },
        )
        await self._ensure_agent_model(agent_id, _message_model(agent_id, {"model": model}))
        result = await self.gateway.request(
            "chat.send",
            {
                "sessionKey": session_key,
                "message": text,
                "toolsAllow": ["memory_search", "memory_get", "session_status"],
                "idempotencyKey": client_message_id,
            },
        )
        send_payload = result.get("payload") or {}
        run_id = str(send_payload.get("runId") or "")
        if not run_id:
            raise RuntimeError("OpenClaw chat.send did not return runId")
        self._active_runs[run_id] = {
            "agent_id": agent_id,
            "client_id": client_id,
            "pane_id": pane_id,
            "session_key": session_key,
            "client_message_id": client_message_id,
            "acc_text": "",
            "started_at": time.monotonic(),
            "last_output_at": time.monotonic(),
        }
        future = asyncio.get_running_loop().create_future()
        self._voice_waiters[run_id] = future
        self.manager.send_to_client(
            client_id,
            {
                "type": "ack",
                "agentId": agent_id,
                "ts": _now(),
                "payload": {
                    "sent": True,
                    "runId": run_id,
                    "clientMessageId": client_message_id,
                    "text": text,
                    "status": send_payload.get("status") or "accepted",
                    "source": "voice",
                    "paneId": pane_id,
                },
            },
        )
        return run_id, future

    async def _send_history(
        self, client_id: str, agent_id: str, limit: int, *, frame_type: str = "history"
    ) -> None:
        messages: list[dict[str, Any]] = []
        if self.gateway.is_connected:
            try:
                result = await self.gateway.request(
                    "chat.history", {"sessionKey": _session_key(agent_id), "limit": limit}
                )
                messages = _history_messages((result.get("payload") or {}).get("messages", []))
            except Exception as exc:
                logger.warning("synapse_hub: chat.history failed for %s: %s", agent_id, exc)
        self.manager.send_to_client(
            client_id,
            {
                "type": frame_type,
                "agentId": agent_id,
                "ts": _now(),
                "payload": {"history": messages, "messages": messages},
            },
        )

    def _drop_agent_runs(self, agent_id: str) -> None:
        """Forget tracked runs for an agent (after abort/reset) so stray
        terminals from the old session can't deliver into the fresh one."""
        for run_id, run in list(self._active_runs.items()):
            if run.get("agent_id") == agent_id:
                self._active_runs.pop(run_id, None)

    async def _handle_abort(self, client_id: str, agent_id: str) -> None:
        try:
            result = await self.gateway.request(
                "chat.abort", {"sessionKey": _session_key(agent_id)}, timeout=10
            )
            payload = result.get("payload") or {}
        except Exception as exc:
            logger.warning("synapse_hub: chat.abort failed for %s: %s", agent_id, exc)
            self._send_error(client_id, str(exc), agent_id)
            return
        self._drop_agent_runs(agent_id)
        self.manager.send_to_client(
            client_id,
            {"type": "aborted", "agentId": agent_id, "ts": _now(), "payload": payload},
        )
        self._broadcast_status(agent_id, "idle")

    async def _handle_reset(self, client_id: str, agent_id: str) -> None:
        """Cleanly stop in-flight work, then start a fresh session.

        ``sessions.reset`` alone rotates the session while a wedged provider
        call keeps the old one hot (the stuck-Codex pattern) — abort first so
        the reset lands on a quiet session, exactly the V1 feel.
        """
        try:
            await self.gateway.request(
                "chat.abort", {"sessionKey": _session_key(agent_id)}, timeout=5
            )
        except Exception as exc:
            logger.warning("synapse_hub: reset abort failed for %s: %s", agent_id, exc)
            self._send_error(client_id, f"Reset aborted: chat.abort failed: {exc}", agent_id)
            return
        self._drop_agent_runs(agent_id)
        try:
            result = await self.gateway.request(
                "sessions.reset", {"key": _session_key(agent_id)}
            )
            payload = result.get("payload") or {}
        except Exception as exc:
            logger.warning("synapse_hub: sessions.reset failed for %s: %s", agent_id, exc)
            self._send_error(client_id, str(exc), agent_id)
            return
        self._last_delivered_text.pop(agent_id, None)
        self._last_delivered_text.pop(_session_key(agent_id), None)
        self._selected_models.pop(agent_id, None)
        self.manager.send_to_client(
            client_id,
            {"type": "reset", "agentId": agent_id, "ts": _now(), "payload": payload},
        )
        # Make the reset visible everywhere: replay the (now empty) history
        # and an idle status to every subscribed pane.
        for subscriber in self.manager.get_subscribers_for_agent(agent_id):
            await self._send_history(subscriber, agent_id, HISTORY_LIMIT)
        self._broadcast_status(agent_id, "idle")

    async def _handle_set_model(self, client_id: str, agent_id: str, payload: dict) -> None:
        gateway = self.gateway if self.gateway.is_connected else None
        result = await _set_agent_model(agent_id, str(payload.get("model") or ""), gateway=gateway)
        if not result.get("ok"):
            self.manager.send_to_client(
                client_id,
                {
                    "type": "error",
                    "agentId": agent_id,
                    "ts": _now(),
                    "payload": {
                        "error": result.get("error") or "Failed to set model",
                        "operation": "set_model",
                    },
                },
            )
            return
        self._selected_models[agent_id] = str(result["model"])
        self.manager.send_to_client(
            client_id,
            {
                "type": "model_set",
                "agentId": agent_id,
                "ts": _now(),
                "payload": {
                    "model": result["model"],
                    "contextWindow": _model_context_window(str(result["model"])),
                    "success": True,
                },
            },
        )
        self._broadcast_status(agent_id, "idle")

    async def _ensure_agent_model(self, agent_id: str, model: str) -> None:
        if not model or self._selected_models.get(agent_id) == model:
            return
        response = await self.gateway.request(
            "sessions.patch", {"key": _session_key(agent_id), "model": model}
        )
        self._selected_models[agent_id] = _patched_model(response, model)

    def _send_error(self, client_id: str, error: str, agent_id: Optional[str] = None) -> None:
        self.manager.send_to_client(
            client_id,
            {"type": "error", "agentId": agent_id, "ts": _now(), "payload": {"error": error}},
        )

    # ── Gateway event fan-out (single reader path — keep O(1), no I/O) ──────

    async def _handle_chat_event(self, frame: dict) -> None:
        payload = frame.get("payload") or {}
        state = payload.get("state")
        run_id = str(payload.get("runId") or "")
        run = self._active_runs.get(run_id) if run_id else None
        # Strict resolution: only the agent's main session (or a run initiated
        # through Synapse) reaches the chat panes. Loose prefix matching would
        # relay cron/voice session output into the live conversation.
        agent_id = (run or {}).get("agent_id") or _chat_agent_id(payload)
        if not agent_id:
            return

        if state == "started":
            if run is None and run_id:
                # Run initiated outside this hub (dispatch, cron, another UI):
                # track it so its terminal still routes to subscribers.
                self._active_runs[run_id] = {
                    "agent_id": agent_id,
                    "client_id": None,
                    "client_message_id": None,
                    "acc_text": "",
                    "started_at": time.monotonic(),
                    "last_output_at": time.monotonic(),
                }
            self._broadcast_status(agent_id, "working", payload)
            return

        if state == "delta":
            # Delta frames carry the true increment in ``deltaText``; the
            # ``message`` key holds the *cumulative* text so far — falling
            # through to it would duplicate already-streamed text.
            text = openclaw_client.extract_message_text(
                payload.get("deltaText") or payload.get("delta")
            ) or ""
            if not text:
                return
            if run is not None:
                run["acc_text"] = (run.get("acc_text") or "") + text
                run["last_output_at"] = time.monotonic()
            pane_id = str((run or {}).get("pane_id") or "")
            chunk = {
                "type": "chunk",
                "agentId": agent_id,
                "paneId": pane_id,
                "ts": _now(),
                "payload": {"text": text, "runId": run_id, "paneId": pane_id},
            }
            if pane_id and run and run.get("client_id") in self.manager.channels:
                self.manager.send_to_client(run["client_id"], chunk)
                return
            for subscriber in self.manager.get_subscribers_for_agent(agent_id):
                self.manager.send_to_client(subscriber, chunk)
            return

        if state in {"final", "aborted", "error"}:
            # Terminal handling may fetch history (gateway RPC) — never on the
            # reader path, or one slow run would stall every agent's stream.
            self._spawn(
                self._handle_terminal(agent_id, run_id, state, payload),
                f"terminal-{run_id[:8] if run_id else agent_id}",
            )

    async def _handle_terminal(
        self, agent_id: str, run_id: str, state: str, payload: dict
    ) -> None:
        run = self._active_runs.pop(run_id, None) if run_id else None
        text = _event_text(payload)
        delivery_key = str((run or {}).get("session_key") or _session_key(agent_id))
        if state == "final" and not text:
            # Prefer this run's own streamed text; fall back to history only
            # when the run produced neither inline nor streamed text. The
            # fallback never re-delivers the previous reply.
            text = ((run or {}).get("acc_text") or "").strip()
            if not text:
                text = await self._history_fallback_text(agent_id, delivery_key)
        if run is None:
            if not text:
                # Untracked terminal with nothing to say — replayed or stale
                # frame (e.g. after a gateway reconnect); drop it.
                return
            if text == self._last_delivered_text.get(delivery_key):
                logger.debug(
                    "synapse_hub: suppressing replayed terminal for run %s",
                    run_id[:8] if run_id else "?",
                )
                return

        pane_id = str((run or {}).get("pane_id") or "")
        fallback_client = (run or {}).get("client_id")
        if pane_id:
            subscribers = [fallback_client] if fallback_client in self.manager.channels else []
        else:
            subscribers = self.manager.get_subscribers_for_agent(agent_id)
            if not subscribers and fallback_client in self.manager.channels:
                subscribers = [fallback_client]

        waiter = self._voice_waiters.pop(run_id, None) if run_id else None
        if waiter is not None and not waiter.done():
            if state == "error":
                waiter.set_exception(RuntimeError(payload.get("errorMessage") or text or "OpenClaw turn failed"))
            elif state == "aborted":
                waiter.cancel()
            else:
                waiter.set_result(text)

        if text:
            self._last_delivered_text[delivery_key] = text
        message_frame = {
            "type": "message",
            "agentId": agent_id,
            "paneId": pane_id,
            "ts": _now(),
            "payload": {
                "role": "assistant",
                "text": text or payload.get("summary") or state,
                "runId": run_id,
                "state": state,
                "paneId": pane_id,
            },
        }
        for subscriber in subscribers:
            self.manager.send_to_client(subscriber, message_frame)
        if subscribers:
            logger.info(
                "synapse_hub: relayed %s response for %s (%d chars, %d clients)",
                state,
                agent_id,
                len(text),
                len(subscribers),
            )
        self._broadcast_status(agent_id, "error" if state == "error" else "idle", payload)

    async def _history_fallback_text(self, agent_id: str, session_key: str) -> str:
        try:
            result = await self.gateway.request(
                "chat.history", {"sessionKey": session_key, "limit": 5}
            )
        except Exception as exc:
            logger.warning("synapse_hub: history fallback failed for %s: %s", agent_id, exc)
            return ""
        for message in reversed((result.get("payload") or {}).get("messages", [])):
            if message.get("role") != "assistant":
                continue
            candidate = openclaw_client.extract_message_text(
                message.get("content", message.get("text", ""))
            )
            if candidate and candidate != self._last_delivered_text.get(session_key):
                return candidate
            return ""  # stale — would replay the prior reply
        return ""

    async def _handle_agent_event(self, frame: dict) -> None:
        payload = frame.get("payload") or {}
        run_id = str(payload.get("runId") or "")
        agent_id = (self._active_runs.get(run_id) or {}).get("agent_id") or _agent_id_from_payload(payload)
        if not agent_id:
            return
        self._broadcast_status(agent_id, payload.get("status") or "idle", payload)

    def _broadcast_status(
        self, agent_id: str, status: str, session: Optional[dict] = None
    ) -> None:
        if not self.manager.channels:
            return
        row = _base_agent(agent_id, synapse_models.get_agent_model_defaults((agent_id,)))
        row["state"] = _state(status)
        row["lastActivity"] = _now()
        if session and _has_context_data(session):
            _merge_session(row, session)
        else:
            row.pop("contextPct", None)
            row.pop("contextUsed", None)
            row.pop("contextMax", None)
        self.manager.broadcast(
            {"type": "status", "agentId": agent_id, "ts": _now(), "payload": row}
        )

    # ── Gateway connection transitions ───────────────────────────────────────

    async def _on_gateway_status(self, snapshot: dict) -> None:
        self.manager.broadcast({"type": "gateway_status", "ts": _now(), "payload": snapshot})
        if snapshot.get("connected"):
            self._spawn(self._resync_after_reconnect(), "resync")
        else:
            # Keep _active_runs: if only the hub's socket blipped, the runs are
            # still live on the gateway and their deltas resume on reconnect
            # (delta routing resolves agents by sessionKey, not run state).
            # Dead runs are reaped by _reap_orphan_runs.
            self.manager.broadcast(
                {
                    "type": "error",
                    "agentId": None,
                    "ts": _now(),
                    "payload": {
                        "error": "OpenClaw gateway connection lost — reconnecting…",
                        "operation": "gateway",
                    },
                }
            )

    async def _resync_after_reconnect(self) -> None:
        """Re-prime fleet status and replay history to subscribed panes.

        Replies that landed while the gateway was unreachable appear without
        a page reload; ``setHistory`` on the frontend also clears any stale
        streaming state.
        """
        self._sessions_cache = None  # force a fresh snapshot post-reconnect
        agents = await self.agent_statuses()
        self.manager.broadcast(
            {"type": "status_all", "ts": _now(), "payload": {"agents": agents}}
        )
        pairs = [
            (client_id, agent_id)
            for client_id, agent_ids in self.manager.subscriptions.items()
            if client_id in self.manager.channels
            for agent_id in agent_ids
        ]
        for client_id, agent_id in pairs:
            await self._send_history(client_id, agent_id, HISTORY_LIMIT)

    # ── Status polling ────────────────────────────────────────────────────────

    async def _status_poll_loop(self) -> None:
        while self._running:
            try:
                if self.gateway.is_connected and self.manager.channels:
                    started = time.monotonic()
                    agents = await self.agent_statuses()
                    STATS["status_poll_ms_last"] = int((time.monotonic() - started) * 1000)
                    self.manager.broadcast(
                        {"type": "status_all", "ts": _now(), "payload": {"agents": agents}}
                    )
                self._reap_orphan_runs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("synapse_hub: status poll failed")
            await asyncio.sleep(STATUS_POLL_INTERVAL)

    def _reap_orphan_runs(self) -> None:
        now = time.monotonic()
        for run_id, run in list(self._active_runs.items()):
            age = now - run.get("started_at", now)
            quiet_for = now - run.get("last_output_at", run.get("started_at", now))
            agent_id = run.get("agent_id") or ""
            last_heartbeat = run.get("heartbeat_at", run.get("started_at", now))
            heartbeat_due = now - last_heartbeat > RUN_HEARTBEAT_INTERVAL_SECONDS
            if quiet_for > RUN_HEARTBEAT_INITIAL_SECONDS and heartbeat_due:
                run["heartbeat_at"] = now
                STATS["run_heartbeats"] += 1
                self._notify_run_watchers(run_id, run, agent_id, age, quiet_for)
            if age > RUN_ORPHAN_TIMEOUT:
                self._active_runs.pop(run_id, None)
                STATS["orphan_runs_reaped"] += 1
                logger.warning(
                    "synapse_hub: reaped orphan run %s for %s (no terminal after %ds)",
                    run_id[:8],
                    agent_id,
                    int(age),
                )
                self._send_orphan_error(run, agent_id)

    def _notify_run_watchers(
        self, run_id: str, run: dict, agent_id: str, age: float, quiet_for: float
    ) -> None:
        recipients = self._run_watchers(run, agent_id)
        frame = {
            "type": "run_heartbeat",
            "agentId": agent_id,
            "paneId": str(run.get("pane_id") or ""),
            "ts": _now(),
            "payload": {
                "runId": run_id,
                "elapsedSeconds": int(age),
                "quietSeconds": int(quiet_for),
                "status": "thinking",
            },
        }
        for recipient in recipients:
            self.manager.send_to_client(recipient, frame)

    def _send_orphan_error(self, run: dict, agent_id: str) -> None:
        frame = {
            "type": "error",
            "agentId": agent_id,
            "ts": _now(),
            "payload": {
                "error": (
                    f"Run for {agent_id} produced no response within {int(RUN_ORPHAN_TIMEOUT)}s "
                    "and was abandoned upstream. Re-send your message (Reset the session if it repeats)."
                ),
                "operation": "run",
            },
        }
        for recipient in self._run_watchers(run, agent_id):
            self.manager.send_to_client(recipient, frame)

    def _run_watchers(self, run: dict, agent_id: str) -> set[str]:
        recipients = set(self.manager.get_subscribers_for_agent(agent_id))
        client_id = run.get("client_id")
        if client_id in self.manager.channels:
            recipients.add(client_id)
        return recipients

    # ── Observability ─────────────────────────────────────────────────────────

    def stats_snapshot(self) -> dict[str, Any]:
        """Counters + live gauges for /api/synapse/hub/stats."""
        requests = STATS.get("gateway_requests", 0)
        avg_ms = (
            round(STATS.get("gateway_request_ms_total", 0) / requests, 1) if requests else 0
        )
        return {
            "counters": dict(STATS),
            "gateway": {
                "connected": self.gateway.is_connected,
                "avgRequestMs": avg_ms,
            },
            "clients": {
                "active": len(self.manager.channels),
                "subscriptions": {
                    cid: sorted(agents)
                    for cid, agents in self.manager.subscriptions.items()
                    if cid in self.manager.channels
                },
            },
            "activeRuns": len(self._active_runs),
            "sessionsCacheAgeSeconds": (
                round(time.monotonic() - self._sessions_cache_at, 1)
                if self._sessions_cache is not None
                else None
            ),
            "running": self._running,
            "ts": _now(),
        }


HUB = SynapseHub()
