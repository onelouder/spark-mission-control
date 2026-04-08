"""
Agent Router — WebSocket multiplexer for multi-agent orchestration

Frame protocol:
{
    "agentId": string,
    "type": "message" | "subscribe" | "unsubscribe" | "status" | "chunk" | "complete" | "error",
    "seq": number (optional),
    "payload": object
}

See: /docs/SYNAPSE_PRD.md
"""

import asyncio
import json
import os
import logging
import ssl
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, Optional, Any, List, Callable
from datetime import datetime

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State as WsState

from openclaw_runtime import get_openclaw_config_path
from synapse_models import explain_model_unavailability, get_model_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
GATEWAY_WS_URL = os.environ.get("MOLTBOT_GATEWAY_WS_URL", "ws://127.0.0.1:18789")
GATEWAY_TOKEN = os.environ.get("MOLTBOT_TOKEN", "1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c")
GATEWAY_CLIENT_ID = os.environ.get("MOLTBOT_GATEWAY_CLIENT_ID", "openclaw-control-ui")
GATEWAY_CLIENT_MODE = os.environ.get("MOLTBOT_GATEWAY_CLIENT_MODE", "ui")
GATEWAY_ORIGIN = os.environ.get("MOLTBOT_GATEWAY_ORIGIN", "http://127.0.0.1:18789")
STATUS_POLL_INTERVAL = 5.0  # seconds
RECONNECT_MAX_DELAY = 30.0  # seconds
REQUESTED_GATEWAY_SCOPES = ["operator.read", "operator.write", "operator.admin"]

CAPABILITY_METHODS = {
    "chatHistory": "chat.history",
    "chatSend": "chat.send",
    "chatAbort": "chat.abort",
    "sessionsList": "sessions.list",
    "sessionsReset": "sessions.reset",
    "sessionsPatch": "sessions.patch",
}

# Agent constellation - maps agent IDs to their session keys
# Organization definitions with colors
ORGANIZATIONS = {
    "internal": {"name": "Internal", "color": "#6366f1"},      # Indigo
    "novvi": {"name": "Novvi", "color": "#10b981"},            # Emerald
    "xcognis": {"name": "X-Cognis", "color": "#f59e0b"},       # Amber
}

AGENT_REGISTRY = {
    # Internal agents
    "jarvis": {"name": "Jarvis", "emoji": "🎩", "model": "opus", "org": "internal", "sessionKey": "agent:jarvis:main"},
    "atlas": {"name": "Atlas", "emoji": "🏛️", "model": "sonnet", "org": "internal", "sessionKey": "agent:atlas:main"},
    "aria": {"name": "Aria", "emoji": "🔬", "model": "sonnet", "org": "internal", "sessionKey": "agent:aria:main"},
    "peter": {"name": "Peter", "emoji": "📊", "model": "sonnet", "org": "internal", "sessionKey": "agent:peter:main"},
    "watson": {"name": "Dr. Watson", "emoji": "🩺", "model": "sonnet", "org": "internal", "sessionKey": "agent:watson:main"},
    "elon": {"name": "ELon", "emoji": "🚀", "model": "sonnet", "org": "internal", "sessionKey": "agent:elon:main"},
    "elon-lite": {"name": "ELon (Lite)", "emoji": "🚀", "model": "gemma", "org": "internal", "sessionKey": "agent:elon-lite:main"},
    "dewey": {"name": "Dewey", "emoji": "📚", "model": "sonnet", "org": "internal", "sessionKey": "agent:dewey:main"},
    "ares": {"name": "Ares", "emoji": "🛡️", "model": "sonnet", "org": "internal", "sessionKey": "agent:ares:main"},
    # Novvi agents
    "willb": {"name": "Will B.", "emoji": "🏢", "model": "sonnet", "org": "novvi", "sessionKey": "agent:willb:main"},
    "jc": {"name": "JC", "emoji": "🧪", "model": "sonnet", "org": "novvi", "sessionKey": "agent:jc:main"},
    # X-Cognis Venture Squad
    "xavier": {"name": "Xavier", "emoji": "🎯", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xavier:main"},
    "xena": {"name": "Xena", "emoji": "🔭", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xena:main"},
    "xander": {"name": "Xander", "emoji": "🤝", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xander:main"},
    "xyla": {"name": "Xyla", "emoji": "🔧", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xyla:main"},
    "ximena": {"name": "Ximena", "emoji": "📞", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:ximena:main"},
    "xerxes": {"name": "Xerxes", "emoji": "💰", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xerxes:main"},
    "xeno": {"name": "Xeno", "emoji": "⚔️", "model": "sonnet", "org": "xcognis", "sessionKey": "agent:xeno:main"},
    # Real Estate
    "todd": {"name": "Todd", "emoji": "🏠", "model": "sonnet", "org": "internal", "sessionKey": "agent:todd:main"},
    # Education
    "donald": {"name": "Donald", "emoji": "🦉", "model": "sonnet", "org": "internal", "sessionKey": "agent:donald:main"},
}


class AgentState(Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class AgentStatus:
    """Lightweight status for FLEET cards"""
    agent_id: str
    name: str = ""
    emoji: str = "\U0001f916"
    state: AgentState = AgentState.IDLE
    task: Optional[str] = None
    context_pct: float = 0.0
    context_max: int = 200000
    model: str = "sonnet"
    last_activity: datetime = field(default_factory=datetime.now)
    session_key: str = ""
    org: str = "internal"
    org_color: str = "#6366f1"

    def to_dict(self) -> dict:
        return {
            "agentId": self.agent_id,
            "name": self.name,
            "emoji": self.emoji,
            "state": self.state.value,
            "task": self.task,
            "contextPct": self.context_pct,
            "contextMax": self.context_max,
            "model": self.model,
            "lastActivity": self.last_activity.isoformat(),
            "sessionKey": self.session_key,
            "org": self.org,
            "orgColor": self.org_color
        }


@dataclass
class Subscription:
    """Track what each client is subscribed to"""
    client_id: str
    status_all: bool = True
    message_agents: Set[str] = field(default_factory=set)  # Multiple agents for multi-chat


class GatewayRPCError(RuntimeError):
    """Structured RPC failure for capability-aware routing."""

    def __init__(self, method: str, error: dict):
        self.method = method
        self.code = str(error.get("code", ""))
        self.message = str(error.get("message", error or "unknown error"))
        self.details = error.get("details") or {}
        super().__init__(f"Gateway RPC {method} failed: {self.message}")

    @property
    def lower_message(self) -> str:
        return self.message.lower()

    def is_missing_scope(self) -> bool:
        return "missing scope" in self.lower_message

    def is_auth_issue(self) -> bool:
        auth_codes = {"AUTH_TOKEN_MISMATCH", "AUTH_DEVICE_TOKEN_MISMATCH", "PAIRING_REQUIRED"}
        return self.code in auth_codes or "unauthorized" in self.lower_message

    def is_not_found(self) -> bool:
        not_found_codes = {"NOT_FOUND", "SESSION_NOT_FOUND"}
        return self.code in not_found_codes or "not found" in self.lower_message


# ---------------------------------------------------------------------------
# GatewayClient — single persistent WebSocket to Moltbot Gateway
# ---------------------------------------------------------------------------

class GatewayClient:
    """Single persistent WebSocket connection to Moltbot Gateway.

    Protocol v3 RPC over ws://localhost:18789.
    Two-phase auth: wait for connect.challenge event, then send connect request
    with protocol version, client info, and token.
    Reconnects with exponential backoff on disconnect.
    """

    def __init__(self, url: str = GATEWAY_WS_URL, token: str = GATEWAY_TOKEN):
        self.url = url
        self.token = token
        self.ws = None
        self._pending: Dict[str, asyncio.Future] = {}  # req id (str) -> future
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._status_handlers: List[Callable] = []
        self._listen_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()
        self._running = False
        self._requested_scopes = list(REQUESTED_GATEWAY_SCOPES)
        self._server_version = ""
        self._protocol: Optional[int] = None
        self._advertised_methods: Set[str] = set()
        self._advertised_events: Set[str] = set()
        self._method_capabilities: Dict[str, Dict[str, Any]] = {}
        self._last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and self.ws.state == WsState.OPEN

    def on_event(self, event_name: str, handler: Callable):
        """Register a handler for Gateway push events (e.g. 'chat', 'agent')."""
        self._event_handlers.setdefault(event_name, []).append(handler)

    def on_status_change(self, handler: Callable):
        """Register a handler for connection or capability changes."""
        self._status_handlers.append(handler)

    def _get_method_capability(self, method: str) -> Dict[str, Any]:
        advertised = method in self._advertised_methods if self._advertised_methods else False
        cap = self._method_capabilities.setdefault(method, {
            "advertised": advertised,
            "allowed": None,
            "reason": None,
        })
        if cap.get("advertised") != advertised:
            cap["advertised"] = advertised
        return cap

    def _set_method_capability(self, method: str, allowed: Optional[bool], reason: Optional[str] = None) -> bool:
        cap = self._get_method_capability(method)
        next_reason = reason or None
        changed = (
            cap.get("advertised") != (method in self._advertised_methods if self._advertised_methods else False)
            or cap.get("allowed") != allowed
            or cap.get("reason") != next_reason
        )
        cap["advertised"] = method in self._advertised_methods if self._advertised_methods else False
        cap["allowed"] = allowed
        cap["reason"] = next_reason
        return changed

    def _apply_capability_aliases(self, methods: List[str], allowed: Optional[bool], reason: Optional[str] = None) -> bool:
        changed = False
        for method in methods:
            changed = self._set_method_capability(method, allowed, reason) or changed
        return changed

    def is_method_available(self, method: str) -> Optional[bool]:
        cap = self._get_method_capability(method)
        if not cap.get("advertised"):
            return False
        return cap.get("allowed")

    def get_status_snapshot(self) -> dict:
        def _capability_dict(method: str) -> dict:
            cap = self._get_method_capability(method)
            return {
                "advertised": bool(cap.get("advertised")),
                "allowed": cap.get("allowed"),
                "reason": cap.get("reason"),
            }

        chat_send = self.is_method_available("chat.send")
        sessions_patch = self.is_method_available("sessions.patch")

        if not self.is_connected:
            mode = "offline"
            summary = self._last_error or "Gateway offline"
        elif chat_send is False:
            mode = "read_only"
            summary = "Gateway connected — chat send unavailable"
        elif sessions_patch is False:
            mode = "limited"
            summary = "Gateway connected — session model control unavailable"
        elif chat_send is None or sessions_patch is None:
            mode = "checking"
            summary = "Gateway connected — verifying capabilities"
        else:
            mode = "online"
            summary = "Gateway connected"

        if self._server_version and mode != "offline":
            summary = f"{summary} (v{self._server_version})"

        return {
            "connected": self.is_connected,
            "serverVersion": self._server_version,
            "protocol": self._protocol,
            "requestedScopes": list(self._requested_scopes),
            "mode": mode,
            "summary": summary,
            "lastError": self._last_error,
            "capabilities": {
                alias: _capability_dict(method)
                for alias, method in CAPABILITY_METHODS.items()
            },
        }

    async def _emit_status_change(self):
        if not self._status_handlers:
            return
        snapshot = self.get_status_snapshot()
        for handler in self._status_handlers:
            try:
                result = handler(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"GatewayClient: status handler error: {e}")

    async def _probe_runtime_capabilities(self):
        if not self.is_connected:
            return

        if "chat.abort" in self._advertised_methods:
            await self._probe_authorization(
                "chat.abort",
                {"sessionKey": "agent:__synapse_capability_probe__:main"},
                alias_methods=["chat.send", "chat.abort"],
            )

        if "sessions.patch" in self._advertised_methods:
            await self._probe_authorization(
                "sessions.patch",
                {"key": "agent:__synapse_capability_probe__:main", "thinkingLevel": "off"},
                alias_methods=["sessions.patch"],
            )

    async def _probe_authorization(self, method: str, params: dict, alias_methods: Optional[List[str]] = None):
        alias_methods = alias_methods or [method]
        try:
            await self._request(method, params)
            # Probe succeeded — mark all aliased methods as allowed
            if self._apply_capability_aliases(alias_methods, True, None):
                await self._emit_status_change()
        except GatewayRPCError as e:
            if e.is_missing_scope() or e.is_auth_issue():
                if self._apply_capability_aliases(alias_methods, False, e.message):
                    await self._emit_status_change()
            elif e.is_not_found():
                if self._apply_capability_aliases(alias_methods, True, None):
                    await self._emit_status_change()
            else:
                if self._apply_capability_aliases(alias_methods, True, e.message):
                    await self._emit_status_change()
        except Exception as e:
            logger.warning(f"GatewayClient: capability probe for {method} failed: {e}")

    async def connect(self):
        """Establish WebSocket and authenticate."""
        self._running = True
        await self._do_connect()

    async def _do_connect(self):
        """Open socket, perform two-phase handshake, start listener."""
        print(f"[GatewayClient] Connecting to {self.url}...")
        try:
            connect_kwargs = {"max_size": 2**21}
            if GATEWAY_ORIGIN:
                connect_kwargs["origin"] = GATEWAY_ORIGIN
            if self.url.startswith("wss://"):
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                connect_kwargs["ssl"] = ssl_ctx
            self.ws = await websockets.connect(self.url, **connect_kwargs)
            print(f"[GatewayClient] WebSocket opened to {self.url}")
            logger.info(f"GatewayClient: WebSocket opened to {self.url}")

            # Phase 1: wait for connect.challenge event (up to 2s)
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2.0)
                challenge = json.loads(raw)
                if challenge.get("event") == "connect.challenge":
                    logger.info("GatewayClient: received connect.challenge")
            except asyncio.TimeoutError:
                logger.warning("GatewayClient: no connect.challenge received, proceeding")

            # Phase 2: send connect request with protocol + client info + auth
            connect_id = str(uuid.uuid4())
            connect_frame = {
                "type": "req",
                "id": connect_id,
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": GATEWAY_CLIENT_ID,
                        "displayName": "Mission Control",
                        "version": "1.0.0",
                        "platform": "linux",
                        "mode": GATEWAY_CLIENT_MODE,
                    },
                    "auth": {"token": self.token},
                    "role": "operator",
                    "scopes": list(self._requested_scopes),
                },
            }
            await self.ws.send(json.dumps(connect_frame))

            # Wait for hello-ok response
            raw = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            hello = json.loads(raw)
            if hello.get("type") == "res" and hello.get("ok"):
                payload = hello.get("payload", {})
                server = payload.get("server", {})
                features = payload.get("features", {})
                self._server_version = server.get("version", "")
                self._protocol = payload.get("protocol")
                self._advertised_methods = set(features.get("methods", []))
                self._advertised_events = set(features.get("events", []))
                for method in CAPABILITY_METHODS.values():
                    self._get_method_capability(method)
                self._last_error = None
                logger.info(f"GatewayClient: authenticated — server v{server.get('version', '?')}")
            else:
                err = hello.get("error", {}).get("message", "unknown error")
                raise ConnectionError(f"Gateway auth failed: {err}")

            # Start listener for ongoing frames
            self._listen_task = asyncio.create_task(self._listen())
            self._connected.set()
            await self._emit_status_change()
            await self._probe_runtime_capabilities()

        except Exception as e:
            print(f"[GatewayClient] CONNECT FAILED: {e}")
            logger.error(f"GatewayClient: connect failed: {e}")
            self._last_error = str(e)
            self._connected.clear()
            if self.ws:
                await self.ws.close()
                self.ws = None
            await self._emit_status_change()
            if self._running:
                self._schedule_reconnect()

    async def disconnect(self):
        """Cleanly shut down the connection."""
        self._running = False
        self._connected.clear()
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        if self.ws:
            await self.ws.close()
            self.ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("GatewayClient disconnected"))
        self._pending.clear()
        self._last_error = "Gateway offline"
        await self._emit_status_change()
        logger.info("GatewayClient: disconnected")

    # -- RPC methods --------------------------------------------------------

    async def list_sessions(self, limit: int = 50, active_minutes: int = 120) -> list:
        """Call sessions.list — returns list of session dicts.
        
        Args:
            limit: Maximum number of sessions to return (default 50)
            active_minutes: Only sessions active within this many minutes (default 120)
        """
        res = await self._request("sessions.list", {
            "limit": limit,
            "activeMinutes": active_minutes,
        })
        return res.get("payload", {}).get("sessions", [])

    async def send_message(self, session_key: str, message: str, idempotency_key: Optional[str] = None) -> dict:
        """Call chat.send — send message to a session. Returns ack with runId.
        
        Note: Model overrides must be set via session_status, not chat.send.
        """
        params = {
            "sessionKey": session_key,
            "message": message,
            "idempotencyKey": idempotency_key or str(uuid.uuid4()),
        }
        return await self._request("chat.send", params)

    async def get_history(self, session_key: str, limit: int = 200) -> list:
        """Call chat.history — fetch message history for a session."""
        res = await self._request("chat.history", {
            "sessionKey": session_key,
            "limit": limit,
        })
        return res.get("payload", {}).get("messages", [])

    async def abort_session(self, session_key: str) -> dict:
        """Call chat.abort — abort any running generation for a session."""
        return await self._request("chat.abort", {
            "sessionKey": session_key,
        })

    async def reset_session(self, session_key: str) -> dict:
        """Call sessions.reset — clear history and start fresh context."""
        return await self._request("sessions.reset", {
            "key": session_key,
        })

    # -- Internal -----------------------------------------------------------

    async def _request(self, method: str, params: dict) -> dict:
        """Send RPC request and await response."""
        if not self.is_connected:
            try:
                await asyncio.wait_for(self._connected.wait(), timeout=10)
            except asyncio.TimeoutError:
                raise ConnectionError("GatewayClient not connected")

        req_id = str(uuid.uuid4())
        frame = {"type": "req", "id": req_id, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        try:
            await self.ws.send(json.dumps(frame))
            result = await asyncio.wait_for(future, timeout=30)
            if not result.get("ok", True):
                err = result.get("error", {})
                rpc_error = GatewayRPCError(method, err if isinstance(err, dict) else {"message": str(err)})
                changed = False
                if rpc_error.is_missing_scope() or rpc_error.is_auth_issue():
                    changed = self._set_method_capability(method, False, rpc_error.message)
                elif rpc_error.code in {"METHOD_NOT_FOUND", "UNKNOWN_METHOD"}:
                    self._advertised_methods.discard(method)
                    changed = self._set_method_capability(method, False, rpc_error.message)
                if changed:
                    await self._emit_status_change()
                raise rpc_error
            if self._set_method_capability(method, True, None):
                await self._emit_status_change()
            return result
        except (ConnectionClosed, ConnectionError) as e:
            logger.warning(f"GatewayClient: request {method} failed: {e}")
            self._connected.clear()
            self._last_error = str(e)
            await self._emit_status_change()
            if self._running:
                self._schedule_reconnect()
            raise
        finally:
            self._pending.pop(req_id, None)

    async def _listen(self):
        """Listen for responses and events, route to futures/handlers."""
        try:
            async for raw in self.ws:
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                ftype = frame.get("type")

                if ftype == "res":
                    req_id = frame.get("id")
                    fut = self._pending.get(req_id)
                    if fut and not fut.done():
                        fut.set_result(frame)

                elif ftype == "event":
                    event_name = frame.get("event", "")
                    handlers = self._event_handlers.get(event_name, [])
                    for handler in handlers:
                        try:
                            result = handler(frame)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.warning(f"GatewayClient: event handler error ({event_name}): {e}")

        except ConnectionClosed as e:
            logger.warning(f"GatewayClient: connection closed: {e}")
            self._last_error = str(e)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"GatewayClient: listener error: {e}")
            self._last_error = str(e)
        finally:
            self._connected.clear()
            await self._emit_status_change()
            if self._running:
                self._schedule_reconnect()

    def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Reconnect with exponential backoff: 1s, 2s, 4s, ... 30s max."""
        delay = 1.0
        while self._running and not self.is_connected:
            logger.info(f"GatewayClient: reconnecting in {delay:.0f}s...")
            await asyncio.sleep(delay)
            if not self._running:
                break
            try:
                await self._do_connect()
                if self.is_connected:
                    logger.info("GatewayClient: reconnected successfully")
                    return
            except Exception as e:
                logger.error(f"GatewayClient: reconnect attempt failed: {e}")
            delay = min(delay * 2, RECONNECT_MAX_DELAY)


# ---------------------------------------------------------------------------
# ConnectionManager — manages Synapse UI client WebSocket connections
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manage WebSocket connections from Synapse UI clients."""

    def __init__(self):
        self.active_connections: Dict[str, Any] = {}  # client_id -> websocket
        self.subscriptions: Dict[str, Subscription] = {}  # client_id -> subscription

    async def connect(self, client_id: str, websocket: Any):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = Subscription(client_id=client_id)
        logger.info(f"Client {client_id} connected")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]
        logger.info(f"Client {client_id} disconnected")

    async def broadcast(self, message: dict):
        """Broadcast to all connected clients"""
        msg_type = message.get("type", "unknown")
        logger.info(f"Broadcasting {msg_type} to {len(self.active_connections)} clients")
        for client_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(message)
                logger.debug(f"Sent {msg_type} to {client_id[:8]}")
            except Exception as e:
                logger.warning(f"Failed to send to {client_id}: {e}")
                self.disconnect(client_id)

    async def send_to_client(self, client_id: str, message: dict):
        """Send to specific client"""
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                msg_type = message.get("type", "unknown")
                logger.info(f"Sending {msg_type} to client {client_id[:8]}")
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to {client_id}: {e}")
                self.disconnect(client_id)

    def get_subscribers_for_agent(self, agent_id: str) -> List[str]:
        """Get client IDs subscribed to a specific agent's messages"""
        return [
            cid for cid, sub in self.subscriptions.items()
            if agent_id in sub.message_agents
        ]


# ---------------------------------------------------------------------------
# AgentRouter — translates Synapse frames to Gateway RPCs
# ---------------------------------------------------------------------------

class AgentRouter:
    """
    Multiplexes Synapse UI WebSocket connections to Moltbot Gateway.

    Uses GatewayClient (single persistent WS) for all Gateway communication.
    Polls sessions.list for status, routes messages via chat.send,
    and fetches history via chat.history.
    
    Subscribes to Gateway 'chat' events to relay agent responses back to
    Synapse clients in real-time.
    """

    def __init__(self):
        self.manager = ConnectionManager()
        self.gateway = GatewayClient()
        self.agents: Dict[str, AgentStatus] = {}
        self._status_task: Optional[asyncio.Task] = None
        self._running = False

        # Track active runs to route terminal events back to the initiating client.
        # runId -> {agent_id, client_id, client_message_id, text, started_at}
        self._active_runs: Dict[str, dict] = {}

        # Runtime model overrides applied through Synapse session controls.
        self._model_overrides: Dict[str, str] = {}

        # Initialize agents from registry
        for agent_id, info in AGENT_REGISTRY.items():
            org_id = info.get("org", "internal")
            org_info = ORGANIZATIONS.get(org_id, ORGANIZATIONS["internal"])
            model = self._normalize_model_id(info["model"]) or info["model"]
            self.agents[agent_id] = AgentStatus(
                agent_id=agent_id,
                name=info["name"],
                emoji=info["emoji"],
                model=model,
                session_key=info["sessionKey"],
                org=org_id,
                org_color=org_info["color"]
            )

    @staticmethod
    def _load_models_from_config():
        """Load valid models, aliases, and display names dynamically from gateway config."""
        catalog = get_model_catalog()
        valid = set(catalog.valid_inputs)
        full_names = dict(catalog.canonical_by_input)
        aliases = dict(catalog.canonical_by_input)
        display_names = {
            model.id: model.label
            for model in catalog.models
        }
        return valid, full_names, aliases, display_names

    @property
    def VALID_MODELS(self):
        valid, _, _, _ = self._load_models_from_config()
        return valid

    @property
    def MODEL_FULL_NAMES(self):
        _, full_names, _, _ = self._load_models_from_config()
        return full_names

    def _get_full_model_name(self, model: str) -> str:
        """Convert short model name to full API name."""
        if not model:
            return None
        # If already a full provider/model path, return as-is
        if "/" in model:
            return model
        return self.MODEL_FULL_NAMES.get(model, model)

    def _normalize_model_id(self, model: str) -> str:
        """Resolve aliases/short IDs to full provider/model IDs."""
        if not model:
            return model
        return get_model_catalog().resolve(model)

    @property
    def MODEL_ALIASES(self):
        _, _, aliases, _ = self._load_models_from_config()
        return aliases

    @property
    def MODEL_DISPLAY_NAMES(self):
        _, _, _, display_names = self._load_models_from_config()
        return display_names

    async def set_agent_model(self, agent_id: str, model: str) -> dict:
        """Set a session-scoped model override for an agent."""
        if agent_id not in self.agents:
            return {"ok": False, "error": "Unknown agent"}
        catalog = get_model_catalog()
        full_model = catalog.resolve(model)
        unavailable_reason = (
            explain_model_unavailability(model)
            or explain_model_unavailability(full_model)
        )
        if unavailable_reason:
            return {"ok": False, "error": unavailable_reason}
        valid_model_ids = {entry.id for entry in catalog.models}
        if full_model not in valid_model_ids:
            return {
                "ok": False,
                "error": f"Invalid model. Choose from: {', '.join(sorted(valid_model_ids))}"
            }
        if self.gateway.is_method_available("sessions.patch") is False:
            snapshot = self.gateway.get_status_snapshot()
            return {
                "ok": False,
                "error": snapshot.get("summary") or "Session model control is unavailable on the current gateway connection.",
            }

        session_key = f"agent:{agent_id}:main"

        try:
            await self.gateway._request("sessions.patch", {
                "key": session_key,
                "model": full_model,
            })
            logger.info(f"Set gateway session model for {agent_id} to {full_model}: True")
        except GatewayRPCError as e:
            logger.error(f"Failed to set gateway session model for {agent_id}: {e}")
            return {"ok": False, "error": e.message}
        except Exception as e:
            logger.error(f"Failed to set gateway session model for {agent_id}: {e}")
            return {"ok": False, "error": str(e)}

        self._model_overrides[agent_id] = full_model

        # Apply immediately to in-memory state
        self.agents[agent_id].model = full_model
        await self._broadcast_all_status()

        return {"ok": True, "agent": agent_id, "model": full_model}

    async def start(self):
        """Start the Gateway connection and status polling."""
        if self._running:
            return
        self._running = True
        
        # Setup event handlers BEFORE connecting
        self._setup_gateway_event_handlers()

        # Connect to Gateway
        try:
            await self.gateway.connect()
        except Exception as e:
            logger.warning(f"AgentRouter: initial Gateway connect failed (will retry): {e}")

        # Start status polling
        self._status_task = asyncio.create_task(self._poll_status_loop())
        logger.info("AgentRouter started")

    async def stop(self):
        """Stop polling and disconnect from Gateway."""
        self._running = False
        if self._status_task:
            self._status_task.cancel()
        await self.gateway.disconnect()
        logger.info("AgentRouter stopped")

    def _setup_gateway_event_handlers(self):
        """Register handlers for Gateway push events to relay to Synapse clients."""
        
        # Handle 'chat' events (agent responses, chunks, etc.)
        self.gateway.on_event("chat", self._handle_gateway_chat_event)
        
        # Handle 'agent' events (run status updates)
        self.gateway.on_event("agent", self._handle_gateway_agent_event)

        # Broadcast connection and capability changes to the UI.
        self.gateway.on_status_change(self._handle_gateway_status_change)
        
        logger.info("AgentRouter: Gateway event handlers registered")

    async def _handle_gateway_status_change(self, snapshot: dict):
        if not self._running:
            return
        await self.manager.broadcast({
            "type": "gateway_status",
            "ts": datetime.now().isoformat(),
            "payload": snapshot,
        })

    async def _broadcast_agent_status(self, agent_id: str):
        agent = self.agents.get(agent_id)
        if not agent:
            return
        await self.manager.broadcast({
            "type": "status",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": agent.to_dict(),
        })

    def _resolve_agent_id(self, session_key: str, run_id: str = "") -> Optional[str]:
        """Resolve an agent id from Gateway chat/session metadata."""
        if session_key.startswith("agent:"):
            parts = session_key.split(":")
            if len(parts) >= 2 and parts[1] in self.agents:
                return parts[1]

        for agent_id, agent in self.agents.items():
            if agent.session_key == session_key:
                return agent_id

        run_info = self._active_runs.get(run_id, {})
        return run_info.get("agent_id")

    def _get_run_recipients(self, agent_id: str, run_id: str) -> tuple[List[str], dict]:
        """Return current subscribers or the initiating client for a run."""
        subscribers = self.manager.get_subscribers_for_agent(agent_id)
        run_info = self._active_runs.get(run_id, {})
        fallback_client = run_info.get("client_id")
        if not subscribers and fallback_client and fallback_client in self.manager.active_connections:
            subscribers = [fallback_client]
        return subscribers, run_info

    async def _send_to_clients(self, client_ids: List[str], message: dict):
        for client_id in client_ids:
            try:
                await self.manager.send_to_client(client_id, message)
            except Exception as e:
                logger.debug(f"Failed to send {message.get('type')} to {client_id[:8]}: {e}")

    async def _handle_gateway_chat_event(self, frame: dict):
        """Handle chat events from Gateway - relay to Synapse clients.
        
        Chat streams now carry enough payload to relay directly on the terminal event
        without scraping history first. We still fall back to history if the final
        payload does not include a displayable assistant message.
        """
        payload = frame.get("payload", {})
        session_key = payload.get("sessionKey", "")
        run_id = payload.get("runId", "")
        state = payload.get("state", "")
        
        # Log chat events at debug level for diagnostics
        logger.debug(f"Chat event: state={state} session={session_key[:20] if session_key else 'none'}")
        
        if state in {"final", "aborted", "error"}:
            asyncio.create_task(self._handle_terminal_response(frame))
            return

        agent_id = self._resolve_agent_id(session_key, run_id)
        if not agent_id:
            logger.debug(f"Chat event for unknown session: {session_key}")
            return
        
        logger.debug(f"Chat event for {agent_id}: state={state}, runId={run_id[:8] if run_id else 'none'}")
        
        # Handle delta events - stream text chunks to Synapse clients
        if state == "delta":
            msg = payload.get("message", {})

            if isinstance(msg, dict):
                delta_text = self._extract_message_text(msg.get("content", msg.get("text", msg)))
            else:
                delta_text = self._extract_message_text(msg or payload.get("delta", payload.get("text", "")))

            if delta_text:
                await self._relay_chunk_to_subscribers(agent_id, delta_text, run_id)
            return
        
        # When run starts, update agent state
        if state == "started":
            agent = self.agents.get(agent_id)
            if agent:
                agent.state = AgentState.WORKING
                agent.last_activity = datetime.now()
                await self._broadcast_agent_status(agent_id)

    async def _relay_chunk_to_subscribers(self, agent_id: str, delta_text: str, run_id: str):
        """Relay streaming text chunk to subscribed Synapse clients."""
        subscribers, run_info = self._get_run_recipients(agent_id, run_id)
        if not subscribers:
            return
        
        logger.debug(f"Chunk: {len(delta_text)} chars to {len(subscribers)} subscribers for {agent_id}")
        
        chunk_frame = {
            "type": "chunk",
            "agentId": agent_id,
            "payload": {
                "text": delta_text,
                "runId": run_id,
                "clientMessageId": run_info.get("client_message_id"),
            }
        }

        await self._send_to_clients(subscribers, chunk_frame)

    async def _handle_terminal_response(self, frame: dict):
        """Relay a terminal chat event and clear run state."""
        payload = frame.get("payload", {})
        session_key = payload.get("sessionKey", "")
        run_id = payload.get("runId", "")
        terminal_state = payload.get("state", "")

        agent_id = self._resolve_agent_id(session_key, run_id)
        if not agent_id:
            logger.debug(f"Terminal event for unknown session: {session_key}")
            return

        subscribers, run_info = self._get_run_recipients(agent_id, run_id)
        agent = self.agents.get(agent_id)
        client_message_id = run_info.get("client_message_id")
        delivered_message = False
        terminal_text = self._extract_message_text(payload.get("message"))
        terminal_ts = payload.get("ts", datetime.now().isoformat())

        try:
            if terminal_state == "final" and not terminal_text and agent:
                messages = await self.gateway.get_history(agent.session_key, limit=5)
                logger.info(f"Fetched {len(messages)} messages from history")
                for msg in reversed(messages):
                    if msg.get("role") != "assistant":
                        continue
                    raw_content = msg.get("content", msg.get("text", ""))
                    terminal_text = self._extract_message_text(raw_content)
                    terminal_ts = msg.get("ts", terminal_ts)
                    if terminal_text:
                        break

            if terminal_text and not self._is_internal_message(terminal_text):
                message_frame = {
                    "type": "message",
                    "agentId": agent_id,
                    "ts": terminal_ts,
                    "payload": {
                        "role": "assistant",
                        "text": terminal_text,
                        "runId": run_id,
                        "clientMessageId": client_message_id,
                    }
                }
                if subscribers:
                    await self._send_to_clients(subscribers, message_frame)
                    delivered_message = True
                logger.info(f"Relayed terminal response for {agent_id} ({len(terminal_text)} chars)")

            if terminal_state == "aborted":
                aborted_frame = {
                    "type": "aborted",
                    "agentId": agent_id,
                    "ts": datetime.now().isoformat(),
                    "payload": {
                        "aborted": True,
                        "runId": run_id,
                        "clientMessageId": client_message_id,
                    }
                }
                if subscribers:
                    await self._send_to_clients(subscribers, aborted_frame)
            elif terminal_state == "error":
                error_text = payload.get("errorMessage") or payload.get("summary") or "Agent run failed"
                error_frame = {
                    "type": "error",
                    "agentId": agent_id,
                    "ts": datetime.now().isoformat(),
                    "payload": {
                        "error": error_text,
                        "operation": "run",
                        "runId": run_id,
                        "clientMessageId": client_message_id,
                    }
                }
                if subscribers:
                    await self._send_to_clients(subscribers, error_frame)
        except Exception as e:
            logger.error(f"Failed to fetch response for {agent_id}: {type(e).__name__}: {e}")

        finish_frame = {
            "type": "run_finished",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": {
                "state": terminal_state,
                "runId": run_id,
                "clientMessageId": client_message_id,
                "deliveredMessage": delivered_message,
            }
        }
        if subscribers:
            await self._send_to_clients(subscribers, finish_frame)

        if agent:
            agent.state = AgentState.ERROR if terminal_state == "error" else AgentState.IDLE
            agent.task = None
            agent.last_activity = datetime.now()
            await self._broadcast_agent_status(agent_id)

        self._active_runs.pop(run_id, None)

    async def _handle_gateway_agent_event(self, frame: dict):
        """Handle agent events from Gateway - status updates."""
        payload = frame.get("payload", {})
        session_key = payload.get("sessionKey", "")
        status = payload.get("status", "")
        
        # Find agent by session key - format is agent:<agent_id>:<session_name>
        agent_id = None
        if session_key.startswith("agent:"):
            parts = session_key.split(":")
            if len(parts) >= 2:
                potential_agent_id = parts[1]
                if potential_agent_id in self.agents:
                    agent_id = potential_agent_id
        
        # Fallback: exact match on stored session_key
        if not agent_id:
            for aid, agent in self.agents.items():
                if agent.session_key == session_key:
                    agent_id = aid
                    break
        
        if not agent_id:
            return
        
        agent = self.agents.get(agent_id)
        if not agent:
            return
        
        # Update state based on event
        if status == "started":
            agent.state = AgentState.WORKING
        elif status in ("completed", "finished"):
            agent.state = AgentState.IDLE
            agent.task = None
        elif status == "error":
            agent.state = AgentState.ERROR
        
        agent.last_activity = datetime.now()
        
        await self._broadcast_agent_status(agent_id)

    async def _poll_status_loop(self):
        """Poll Gateway sessions.list and broadcast status updates."""
        while self._running:
            try:
                await self._update_agent_statuses()
            except Exception as e:
                logger.error(f"Status poll error: {e}")
            await asyncio.sleep(STATUS_POLL_INTERVAL)

    async def _update_agent_statuses(self):
        """Fetch live status from Gateway via sessions.list RPC."""
        if not self.gateway.is_connected:
            # Fall back to file-based status if Gateway is down
            await self._update_agent_statuses_from_file()
            return
        if self.gateway.is_method_available("sessions.list") is False:
            await self._update_agent_statuses_from_file()
            return

        try:
            sessions = await self.gateway.list_sessions()
            if sessions:
                logger.info(f"Got {len(sessions)} sessions, first keys: {list(sessions[0].keys()) if sessions else 'none'}")
        except Exception as e:
            logger.warning(f"sessions.list failed, falling back to file: {e}")
            await self._update_agent_statuses_from_file()
            return

        # Build a lookup by session key
        session_map = {}
        for sess in sessions:
            key = sess.get("sessionKey") or sess.get("key") or sess.get("id", "")
            if key:
                session_map[key] = sess

        for agent_id, agent in self.agents.items():
            sess = session_map.get(agent.session_key)
            if sess:
                # Map Gateway session state to our AgentState
                gw_status = sess.get("status", "idle")
                state_map = {
                    "idle": AgentState.IDLE,
                    "active": AgentState.WORKING,
                    "working": AgentState.WORKING,
                    "running": AgentState.WORKING,
                    "blocked": AgentState.BLOCKED,
                    "waiting": AgentState.BLOCKED,
                    "error": AgentState.ERROR,
                    "done": AgentState.COMPLETE,
                }
                agent.state = state_map.get(gw_status, AgentState.IDLE)
                # Calculate context percentage from tokens
                context_tokens = sess.get("contextTokens", 200000)
                total_tokens = sess.get("totalTokens", 0)
                agent.context_max = context_tokens
                if context_tokens > 0:
                    agent.context_pct = round(total_tokens / context_tokens * 100, 2)
                else:
                    agent.context_pct = 0
                if sess.get("task"):
                    agent.task = sess["task"]
                if sess.get("model"):
                    agent.model = self._normalize_model_id(sess["model"])
                # Apply local model override if set
                if agent_id in self._model_overrides:
                    agent.model = self._normalize_model_id(self._model_overrides[agent_id])

        await self._broadcast_all_status()

    async def _update_agent_statuses_from_file(self):
        """Fallback: read status from agent_status.json (cron-updated)."""
        status_file = os.path.join(os.path.dirname(__file__), "data", "agent_status.json")

        try:
            if not os.path.exists(status_file):
                return

            with open(status_file, 'r') as f:
                data = json.load(f)

            raw_agents = data.get("agents", [])
            if isinstance(raw_agents, dict):
                agent_rows = []
                for agent_id, payload in raw_agents.items():
                    if isinstance(payload, dict):
                        row = dict(payload)
                        row.setdefault("agentId", agent_id)
                        agent_rows.append(row)
            elif isinstance(raw_agents, list):
                agent_rows = [row for row in raw_agents if isinstance(row, dict)]
            else:
                agent_rows = []

            for agent_data in agent_rows:
                agent_id = agent_data.get("agentId") or agent_data.get("id")
                if agent_id in self.agents:
                    agent = self.agents[agent_id]
                    state_map = {
                        "idle": AgentState.IDLE,
                        "active": AgentState.WORKING,
                        "working": AgentState.WORKING,
                        "blocked": AgentState.BLOCKED,
                        "error": AgentState.ERROR,
                    }
                    agent.context_pct = agent_data.get("contextPct", agent_data.get("context_pct", 0))
                    agent.state = state_map.get(agent_data.get("state", agent_data.get("status", "idle")), AgentState.IDLE)
                    agent.session_key = agent_data.get("sessionKey", agent_data.get("session_key", agent.session_key))
                    if agent_data.get("model"):
                        agent.model = self._normalize_model_id(agent_data.get("model"))
                    # Apply local model override if set
                    if agent_id in self._model_overrides:
                        agent.model = self._normalize_model_id(self._model_overrides[agent_id])
                    if agent_data.get("emoji"):
                        agent.emoji = agent_data["emoji"]
                    if agent_data.get("name"):
                        agent.name = agent_data["name"]

            await self._broadcast_all_status()

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in agent_status.json: {e}")
        except Exception as e:
            logger.error(f"Failed to read agent status: {e}")

    async def _broadcast_all_status(self):
        """Broadcast all agent statuses to clients"""
        status_frame = {
            "type": "status_all",
            "ts": datetime.now().isoformat(),
            "payload": {
                "agents": [agent.to_dict() for agent in self.agents.values()],
                "gateway": self.gateway.get_status_snapshot(),
            }
        }
        await self.manager.broadcast(status_frame)

    async def handle_connect(self, client_id: str, websocket: Any):
        """Handle new client connection"""
        await self.manager.connect(client_id, websocket)

        connected_frame = {
            "type": "connected",
            "ts": datetime.now().isoformat(),
            "payload": {
                "agents": [agent.to_dict() for agent in self.agents.values()],
                "gateway": self.gateway.get_status_snapshot(),
            }
        }
        await self.manager.send_to_client(client_id, connected_frame)

    def handle_disconnect(self, client_id: str):
        """Handle client disconnect"""
        self.manager.disconnect(client_id)

    async def handle_frame(self, client_id: str, frame: dict) -> Optional[dict]:
        """Process incoming frame from client"""
        frame_type = frame.get("type")
        agent_id = frame.get("agentId")
        payload = frame.get("payload", {})
        logger.info(f"Frame from {client_id[:8]}: type={frame_type}, agentId={agent_id}")

        if frame_type == "subscribe":
            return await self._handle_subscribe(client_id, agent_id, payload)
        elif frame_type == "unsubscribe":
            return await self._handle_unsubscribe(client_id, agent_id)
        elif frame_type == "message":
            return await self._handle_message(client_id, agent_id, payload)
        elif frame_type == "history":
            return await self._handle_history(client_id, agent_id, payload)
        elif frame_type == "abort":
            return await self._handle_abort(client_id, agent_id)
        elif frame_type == "reset":
            return await self._handle_reset(client_id, agent_id)
        elif frame_type == "set_model":
            return await self._handle_set_model(client_id, agent_id, payload)
        elif frame_type == "ping":
            return {"type": "pong", "ts": datetime.now().isoformat()}
        else:
            return {"type": "error", "payload": {"error": f"Unknown frame type: {frame_type}"}}

    async def _handle_subscribe(self, client_id: str, agent_id: str, payload: dict) -> dict:
        """Subscribe client to an agent's message stream"""
        sub = self.manager.subscriptions.get(client_id)
        if not sub:
            return {"type": "error", "payload": {"error": "Client not found"}}

        sub.message_agents.add(agent_id)
        logger.info(f"Client {client_id[:8]} subscribed to {agent_id} (now: {sub.message_agents})")

        history = await self._fetch_agent_history(agent_id)

        return {
            "type": "subscribed",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": {
                "focused": True,
                "history": history
            }
        }

    async def _handle_unsubscribe(self, client_id: str, agent_id: str) -> dict:
        """Unsubscribe client from agent's message stream"""
        sub = self.manager.subscriptions.get(client_id)
        if sub and agent_id in sub.message_agents:
            sub.message_agents.discard(agent_id)

        return {
            "type": "unsubscribed",
            "agentId": agent_id,
            "ts": datetime.now().isoformat()
        }

    async def _handle_message(self, client_id: str, agent_id: str, payload: dict) -> dict:
        """Forward message to agent via GatewayClient WebSocket RPC."""
        text = str(payload.get("text", "") or "").strip()
        client_message_id = str(payload.get("clientMessageId") or uuid.uuid4())
        if not text:
            return {"type": "error", "payload": {"error": "Empty message"}}
        if self.gateway.is_method_available("chat.send") is False:
            snapshot = self.gateway.get_status_snapshot()
            return {
                "type": "error",
                "agentId": agent_id,
                "payload": {
                    "error": snapshot.get("summary") or "Gateway chat send is unavailable.",
                    "operation": "message",
                    "clientMessageId": client_message_id,
                    "gateway": snapshot,
                }
            }

        agent = self.agents.get(agent_id)
        if not agent:
            return {"type": "error", "payload": {"error": f"Unknown agent: {agent_id}"}}

        unavailable_reason = explain_model_unavailability(agent.model)
        if unavailable_reason:
            return {
                "type": "error",
                "agentId": agent_id,
                "payload": {
                    "error": unavailable_reason,
                    "operation": "message",
                    "clientMessageId": client_message_id,
                    "model": agent.model,
                    "gateway": self.gateway.get_status_snapshot(),
                }
            }

        # Forward via Gateway WebSocket RPC
        # Note: chat.send returns immediately with {runId, status: "started"}
        # Actual response comes via Gateway 'chat' events (handled by _setup_gateway_event_handlers)
        # Model overrides are set via session_status, not per-message
        
        try:
            result = await self.gateway.send_message(
                agent.session_key,
                text,
                idempotency_key=client_message_id,
            )
            run_id = result.get("payload", {}).get("runId", "")
            accepted_at = datetime.now().isoformat()

            agent.state = AgentState.WORKING
            agent.task = text[:50]
            agent.last_activity = datetime.now()
            await self._broadcast_agent_status(agent_id)
            
            # Track this run so we can route responses back
            if run_id:
                self._active_runs[run_id] = {
                    "agent_id": agent_id,
                    "client_id": client_id,
                    "client_message_id": client_message_id,
                    "text": text,
                    "started_at": accepted_at,
                }

            return {
                "type": "ack",
                "agentId": agent_id,
                "payload": {
                    "sent": True,
                    "runId": run_id,
                    "clientMessageId": client_message_id,
                    "text": text,
                    "ts": accepted_at,
                }
            }

        except GatewayRPCError as e:
            agent.state = AgentState.IDLE if (e.is_missing_scope() or e.is_auth_issue()) else AgentState.ERROR
            agent.task = None
            agent.last_activity = datetime.now()
            await self._broadcast_agent_status(agent_id)
            logger.error(f"Failed to send message to {agent_id}: {e}")
            return {
                "type": "error",
                "agentId": agent_id,
                "payload": {
                    "error": e.message,
                    "code": e.code,
                    "operation": "message",
                    "clientMessageId": client_message_id,
                    "gateway": self.gateway.get_status_snapshot(),
                }
            }
        except Exception as e:
            agent.state = AgentState.ERROR
            agent.task = None
            agent.last_activity = datetime.now()
            await self._broadcast_agent_status(agent_id)
            logger.error(f"Failed to send message to {agent_id}: {e}")
            return {
                "type": "error",
                "agentId": agent_id,
                "payload": {
                    "error": str(e),
                    "operation": "message",
                    "clientMessageId": client_message_id,
                    "gateway": self.gateway.get_status_snapshot(),
                }
            }

    async def _handle_history(self, client_id: str, agent_id: str, payload: dict) -> dict:
        """Fetch message history for agent"""
        limit = payload.get("limit", 100)
        history = await self._fetch_agent_history(agent_id, limit)

        return {
            "type": "history",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": {"messages": history, "hasMore": len(history) >= limit}
        }

    async def _handle_abort(self, client_id: str, agent_id: str) -> dict:
        """Abort any running generation for an agent"""
        agent = self.agents.get(agent_id)
        if not agent:
            return {"type": "error", "payload": {"error": f"Unknown agent: {agent_id}"}}

        try:
            result = await self.gateway.abort_session(agent.session_key)
            aborted = result.get("payload", {}).get("aborted", False)
            
            # Update agent state if aborted
            if aborted:
                agent.state = AgentState.IDLE
                agent.task = None
                await self.manager.broadcast({
                    "type": "status",
                    "agentId": agent_id,
                    "ts": datetime.now().isoformat(),
                    "payload": agent.to_dict()
                })
            
            return {
                "type": "aborted",
                "agentId": agent_id,
                "ts": datetime.now().isoformat(),
                "payload": {"aborted": aborted}
            }
        except Exception as e:
            logger.error(f"Failed to abort {agent_id}: {e}")
            return {"type": "error", "payload": {"error": str(e)}}

    async def _handle_reset(self, client_id: str, agent_id: str) -> dict:
        """Reset session - clear history and start fresh context"""
        agent = self.agents.get(agent_id)
        if not agent:
            return {"type": "error", "payload": {"error": f"Unknown agent: {agent_id}"}}

        try:
            result = await self.gateway.reset_session(agent.session_key)
            
            # Update agent state
            agent.state = AgentState.IDLE
            agent.task = None
            await self.manager.broadcast({
                "type": "status",
                "agentId": agent_id,
                "ts": datetime.now().isoformat(),
                "payload": agent.to_dict()
            })
            
            return {
                "type": "reset",
                "agentId": agent_id,
                "ts": datetime.now().isoformat(),
                "payload": {"reset": True}
            }
        except Exception as e:
            logger.error(f"Failed to reset {agent_id}: {e}")
            return {"type": "error", "payload": {"error": str(e)}}

    async def _handle_set_model(self, client_id: str, agent_id: str, payload: dict) -> dict:
        """Set model for an agent"""
        if not agent_id:
            return {"type": "error", "payload": {"error": "Agent ID required", "operation": "set_model"}}
        
        model = payload.get("model")
        if not model:
            return {"type": "error", "agentId": agent_id, "payload": {"error": "Model required", "operation": "set_model"}}
        
        try:
            result = await self.set_agent_model(agent_id, model)
            if not result.get("ok", False):
                return {
                    "type": "error",
                    "agentId": agent_id,
                    "payload": {
                        "error": result.get("error", "Failed to set model"),
                        "operation": "set_model",
                        "gateway": self.gateway.get_status_snapshot(),
                    }
                }
            
            # Broadcast updated status to all clients
            agent = self.agents.get(agent_id)
            if agent:
                agent.model = result.get("model", model)
                await self.manager.broadcast({
                    "type": "status",
                    "agentId": agent_id,
                    "ts": datetime.now().isoformat(),
                    "payload": agent.to_dict()
                })
            
            return {
                "type": "model_set",
                "agentId": agent_id,
                "ts": datetime.now().isoformat(),
                "payload": {"model": result.get("model", model), "success": True}
            }
        except Exception as e:
            logger.error(f"Failed to set model for {agent_id}: {e}")
            return {
                "type": "error",
                "agentId": agent_id,
                "payload": {
                    "error": str(e),
                    "operation": "set_model",
                    "gateway": self.gateway.get_status_snapshot(),
                }
            }

    # Roles that represent actual conversation turns (not tool machinery)
    _CHAT_ROLES = {"user", "assistant"}

    async def _fetch_agent_history(self, agent_id: str, limit: int = 100) -> List[dict]:
        """Fetch conversation history via GatewayClient WebSocket RPC.

        Filters out non-conversation messages (toolResult, toolCall, system)
        so the chat view only shows human-readable turns.
        """
        agent = self.agents.get(agent_id)
        if not agent:
            return []
        if self.gateway.is_method_available("chat.history") is False:
            return []

        try:
            messages = await self.gateway.get_history(agent.session_key, limit)
            result = []
            for msg in messages:
                role = msg.get("role", "")
                if role not in self._CHAT_ROLES:
                    continue  # Skip toolResult, toolCall, system, etc.
                text = self._extract_message_text(msg.get("content", msg.get("text", "")))
                if not text:  # Skip empty messages
                    continue
                # Skip internal/system messages (heartbeats, cron prompts, NO_REPLY, etc.)
                if self._is_internal_message(text, role):
                    continue
                result.append({
                    "role": role,
                    "text": text,
                    "ts": msg.get("ts", datetime.now().isoformat())
                })
            return result
        except GatewayRPCError as e:
            if e.is_missing_scope() or e.is_auth_issue():
                logger.info(f"Skipping history fetch for {agent_id}: {e.message}")
                return []
            logger.error(f"Failed to fetch history for {agent_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch history for {agent_id}: {e}")
            return []
    
    def _is_internal_message(self, text: str, role: str = None) -> bool:
        """Check if a message is internal/system and should be hidden from chat.
        
        Filters out:
        - Heartbeat prompts and responses
        - Cron system prompts
        - Pre-compaction flush prompts
        - NO_REPLY messages
        """
        if not text:
            return False
        
        text_lower = text.strip().lower()
        text_stripped = text.strip()
        
        # Skip heartbeat-related messages
        if "heartbeat_ok" in text_lower or text_stripped == "HEARTBEAT_OK":
            return True
        if "read heartbeat.md" in text_lower:
            return True
        
        # Skip compaction/system prompts
        if "pre-compaction memory flush" in text_lower:
            return True
        if "session nearing auto-compaction" in text_lower:
            return True
        
        # Skip cron summarization prompts
        if "summarize this naturally for the user" in text_lower:
            return True
        
        # Skip NO_REPLY responses (but not messages that contain NO_REPLY as part of instructions)
        if text_stripped == "NO_REPLY":
            return True
        
        return False
    
    def _extract_message_text(self, content) -> str:
        """Extract plain text from message content.
        
        Content can be:
        - A string (simple case)
        - A list of content blocks (may include thinking, text, toolCall, toolResult, etc.)
        
        Only extracts 'text' type blocks, skips everything else (thinking, tool calls, tool results).
        """
        def _extract(value, depth: int = 0) -> str:
            if value is None:
                return ""
            if depth > 6:
                return ""

            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return ""

                # OpenClaw may wrap text payloads as JSON strings in newer builds.
                if stripped[0] in "{[":
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        parsed = None
                    if parsed is not None:
                        extracted = _extract(parsed, depth + 1)
                        if extracted:
                            return extracted

                # Skip short tool-output markers.
                if stripped.startswith(("```", "Successfully", "(no output)", "Command")) and len(stripped) < 100:
                    return ""
                return value

            if isinstance(value, list):
                parts = []
                for item in value:
                    text = _extract(item, depth + 1)
                    if text:
                        parts.append(text)
                return "\n".join(parts).strip()

            if isinstance(value, dict):
                block_type = value.get("type", "")
                if block_type == "text":
                    return _extract(value.get("text", ""), depth + 1)

                for key in ("text", "delta", "content", "message", "output"):
                    if key in value:
                        text = _extract(value.get(key), depth + 1)
                        if text:
                            return text

                nested = []
                for key, nested_value in value.items():
                    if isinstance(nested_value, (dict, list)) and key not in {"toolCall", "toolResult", "metadata"}:
                        text = _extract(nested_value, depth + 1)
                        if text:
                            nested.append(text)
                return "\n".join(nested).strip()

            return str(value) if value else ""

        return _extract(content)

    def get_all_status(self) -> List[dict]:
        """Get status of all registered agents"""
        return [agent.to_dict() for agent in self.agents.values()]


# Singleton instance
router = AgentRouter()


# FastAPI integration - call these from app.py
async def synapse_websocket_endpoint(websocket: Any, client_id: str):
    """
    WebSocket endpoint for Synapse.

    Usage in app.py:
        from agent_router import synapse_websocket_endpoint, router as agent_router
        from fastapi import WebSocket, WebSocketDisconnect
        import uuid

        @app.on_event("startup")
        async def startup_event():
            await agent_router.start()

        @app.on_event("shutdown")
        async def shutdown_event():
            await agent_router.stop()

        @app.websocket("/api/synapse/ws")
        async def synapse_ws(websocket: WebSocket):
            client_id = str(uuid.uuid4())
            await synapse_websocket_endpoint(websocket, client_id)
    """
    await router.handle_connect(client_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            response = await router.handle_frame(client_id, data)
            if response:
                await websocket.send_json(response)
    except Exception as e:
        logger.info(f"WebSocket closed for {client_id}: {e}")
    finally:
        router.handle_disconnect(client_id)


# REST endpoint for status (alternative to WebSocket)
def get_fleet_status() -> dict:
    """Get current fleet status for REST API"""
    return {
        "agents": router.get_all_status(),
        "ts": datetime.now().isoformat()
    }


# ---------------------------------------------------------------------------
# Agent workspace config — read/write SOUL.md, AGENTS.md, WORKING.md
# Revisions stored in data/revisions/{agentId}/{filename}.{rev}.md
# ---------------------------------------------------------------------------

import shutil
import glob as _glob
from pathlib import Path

REVISIONS_DIR = os.path.join(os.path.dirname(__file__), "data", "revisions")
MAX_REVISIONS = 10

# Editable files (versioned on save)
EDITABLE_FILES = {"soulMd": "SOUL.md", "agentsMd": "AGENTS.md"}
# Read-only files
READONLY_FILES = {"workingMd": "WORKING.md"}
ALL_FILES = {**EDITABLE_FILES, **READONLY_FILES}

# Load agent workspace paths from openclaw.json
_AGENT_WORKSPACES: Dict[str, str] = {}


def _load_agent_workspaces():
    """Parse openclaw.json to map agent IDs to workspace paths."""
    global _AGENT_WORKSPACES
    config_path = get_openclaw_config_path()
    _AGENT_WORKSPACES = {}
    if not os.path.exists(config_path):
        logger.warning(f"openclaw.json not found at {config_path}")
        return

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to read openclaw.json at {config_path}: {exc}")
        return

    default_ws = data.get("agents", {}).get("defaults", {}).get("workspace", "")
    for agent in data.get("agents", {}).get("list", []):
        aid = agent.get("id")
        if not aid:
            continue
        _AGENT_WORKSPACES[aid] = agent.get("workspace", default_ws)
    logger.info(f"Loaded {len(_AGENT_WORKSPACES)} agent workspaces")


_load_agent_workspaces()


def _get_workspace(agent_id: str) -> Optional[str]:
    """Return workspace path for an agent, or None."""
    ws = _AGENT_WORKSPACES.get(agent_id)
    if ws and os.path.isdir(ws):
        return ws
    return None


def _create_revision(agent_id: str, filename: str, workspace: str):
    """Copy current file to revisions dir before overwrite. Keep newest MAX_REVISIONS."""
    src = os.path.join(workspace, filename)
    if not os.path.exists(src):
        return

    rev_dir = os.path.join(REVISIONS_DIR, agent_id)
    os.makedirs(rev_dir, exist_ok=True)

    # Find next revision number
    base = filename.replace(".md", "")
    existing = sorted(_glob.glob(os.path.join(rev_dir, f"{base}.*.md")))
    if existing:
        # Extract highest rev number
        last = existing[-1]
        try:
            highest = int(Path(last).stem.split(".")[-1])
        except ValueError:
            highest = 0
        next_rev = highest + 1
    else:
        next_rev = 1

    # Copy current file as revision
    rev_path = os.path.join(rev_dir, f"{base}.{next_rev}.md")
    shutil.copy2(src, rev_path)

    # Prune: keep only newest MAX_REVISIONS
    all_revs = sorted(_glob.glob(os.path.join(rev_dir, f"{base}.*.md")))
    if len(all_revs) > MAX_REVISIONS:
        for old in all_revs[:-MAX_REVISIONS]:
            os.remove(old)


def get_agent_config(agent_id: str) -> Optional[dict]:
    """Read SOUL.md, AGENTS.md, WORKING.md from agent workspace."""
    if agent_id not in AGENT_REGISTRY:
        return None
    ws = _get_workspace(agent_id)
    if not ws:
        return None

    result = {}
    for key, filename in ALL_FILES.items():
        filepath = os.path.join(ws, filename)
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                result[key] = f.read()
        else:
            result[key] = ""
    result["workspace"] = ws
    result["editableFields"] = list(EDITABLE_FILES.keys())
    return result


def save_agent_config(agent_id: str, config: dict) -> Optional[dict]:
    """Save editable workspace files with versioning. Rejects read-only fields."""
    if agent_id not in AGENT_REGISTRY:
        return None
    ws = _get_workspace(agent_id)
    if not ws:
        return None

    saved = {}
    for key, filename in EDITABLE_FILES.items():
        if key in config:
            # Create revision of current file before overwriting
            _create_revision(agent_id, filename, ws)
            filepath = os.path.join(ws, filename)
            with open(filepath, "w") as f:
                f.write(config[key])
            saved[key] = config[key]

    return saved
