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
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, Optional, Any, List, Callable
from datetime import datetime

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State as WsState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
GATEWAY_WS_URL = os.environ.get("MOLTBOT_GATEWAY_WS_URL", "ws://localhost:18789")
GATEWAY_TOKEN = os.environ.get("MOLTBOT_TOKEN", "1eba89d56887b8dd1845e1d0898935f8ad378ffc28dd556c")
STATUS_POLL_INTERVAL = 5.0  # seconds
RECONNECT_MAX_DELAY = 30.0  # seconds

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
        self._listen_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and self.ws.state == WsState.OPEN

    def on_event(self, event_name: str, handler: Callable):
        """Register a handler for Gateway push events (e.g. 'chat', 'agent')."""
        self._event_handlers.setdefault(event_name, []).append(handler)

    async def connect(self):
        """Establish WebSocket and authenticate."""
        self._running = True
        await self._do_connect()

    async def _do_connect(self):
        """Open socket, perform two-phase handshake, start listener."""
        print(f"[GatewayClient] Connecting to {self.url}...")
        try:
            self.ws = await websockets.connect(
                self.url,
                max_size=2**21,
                origin="http://localhost:3000"
            )
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
                        "id": "openclaw-control-ui",
                        "displayName": "Mission Control",
                        "version": "1.0.0",
                        "platform": "linux",
                        "mode": "ui",
                    },
                    "auth": {"token": self.token},
                    "role": "operator",
                    "scopes": ["operator.admin"],
                },
            }
            await self.ws.send(json.dumps(connect_frame))

            # Wait for hello-ok response
            raw = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            hello = json.loads(raw)
            if hello.get("type") == "res" and hello.get("ok"):
                server = hello.get("payload", {}).get("server", {})
                logger.info(f"GatewayClient: authenticated — server v{server.get('version', '?')}")
            else:
                err = hello.get("error", {}).get("message", "unknown error")
                raise ConnectionError(f"Gateway auth failed: {err}")

            # Start listener for ongoing frames
            self._listen_task = asyncio.create_task(self._listen())
            self._connected.set()

        except Exception as e:
            print(f"[GatewayClient] CONNECT FAILED: {e}")
            logger.error(f"GatewayClient: connect failed: {e}")
            self._connected.clear()
            if self.ws:
                await self.ws.close()
                self.ws = None
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

    async def send_message(self, session_key: str, message: str) -> dict:
        """Call chat.send — send message to a session. Returns ack with runId.
        
        Note: Model overrides must be set via session_status, not chat.send.
        """
        idempotency_key = str(uuid.uuid4())
        params = {
            "sessionKey": session_key,
            "message": message,
            "idempotencyKey": idempotency_key,
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
                raise RuntimeError(f"Gateway RPC {method} failed: {err.get('message', err)}")
            return result
        except (ConnectionClosed, ConnectionError) as e:
            logger.warning(f"GatewayClient: request {method} failed: {e}")
            self._connected.clear()
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
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"GatewayClient: listener error: {e}")
        finally:
            self._connected.clear()
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

        # Track active runs to route responses back to correct clients
        # runId -> {agent_id, client_id, started_at}
        self._active_runs: Dict[str, dict] = {}

        # Local model overrides (persisted to data/model_overrides.json)
        self._model_overrides: Dict[str, str] = {}
        self._load_model_overrides()

        # Initialize agents from registry
        for agent_id, info in AGENT_REGISTRY.items():
            org_id = info.get("org", "internal")
            org_info = ORGANIZATIONS.get(org_id, ORGANIZATIONS["internal"])
            # Apply local model override if it exists
            model = self._model_overrides.get(agent_id, info["model"])
            self.agents[agent_id] = AgentStatus(
                agent_id=agent_id,
                name=info["name"],
                emoji=info["emoji"],
                model=model,
                session_key=info["sessionKey"],
                org=org_id,
                org_color=org_info["color"]
            )

    def _load_model_overrides(self):
        """Load model overrides from persistent JSON file."""
        path = os.path.join(os.path.dirname(__file__), "data", "model_overrides.json")
        try:
            with open(path) as f:
                self._model_overrides = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._model_overrides = {}

    def _save_model_overrides(self):
        """Save model overrides to persistent JSON file."""
        path = os.path.join(os.path.dirname(__file__), "data", "model_overrides.json")
        with open(path, 'w') as f:
            json.dump(self._model_overrides, f, indent=2)

    @staticmethod
    def _load_models_from_config():
        """Load valid models, aliases, and display names dynamically from gateway config."""
        try:
            config_path = os.path.expanduser("~/.openclaw/openclaw.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
            models_cfg = config.get("agents", {}).get("defaults", {}).get("models", {})
            valid = set()
            aliases = {}
            full_names = {}
            display_names = {}
            for model_id, info in models_cfg.items():
                alias = info.get("alias", "")
                # model_id is already the full qualified name (e.g. "anthropic/claude-opus-4-6", "google/gemini-3-pro-preview")
                # Extract short name: strip provider prefix
                parts = model_id.split("/", 1)
                short = parts[1] if len(parts) > 1 else model_id
                
                # Accept full id, short id, and alias — all resolve to the full model_id
                valid.add(model_id)
                valid.add(short)
                full_names[model_id] = model_id
                full_names[short] = model_id
                aliases[model_id] = model_id
                aliases[short] = model_id
                display_names[model_id] = alias or short
                if alias:
                    valid.add(alias)
                    full_names[alias] = model_id
                    aliases[alias] = model_id
            return valid, full_names, aliases, display_names
        except Exception:
            # Fallback if config unreadable
            return {"opus", "sonnet"}, {}, {}, {}

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

    @property
    def MODEL_ALIASES(self):
        _, _, aliases, _ = self._load_models_from_config()
        return aliases

    @property
    def MODEL_DISPLAY_NAMES(self):
        _, _, _, display_names = self._load_models_from_config()
        return display_names

    async def set_agent_model(self, agent_id: str, model: str) -> dict:
        """Set model override for an agent — persists to gateway config + active session."""
        if agent_id not in self.agents:
            return {"ok": False, "error": "Unknown agent"}
        if model not in self.VALID_MODELS:
            return {"ok": False, "error": f"Invalid model. Choose from: {', '.join(self.VALID_MODELS)}"}

        # Resolve alias to full model name for gateway
        full_model = self.MODEL_ALIASES.get(model, model)

        # 1. Persist to gateway config (survives session resets)
        try:
            config_path = os.path.expanduser("~/.openclaw/openclaw.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            agents_list = config.get("agents", {}).get("list", [])
            for agent_cfg in agents_list:
                if agent_cfg.get("id") == agent_id:
                    agent_cfg["model"] = full_model
                    break
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info(f"Persisted model {full_model} for {agent_id} to gateway config")
        except Exception as e:
            logger.error(f"Failed to persist model to config for {agent_id}: {e}")
            # Continue — session override still useful even if config write fails

        # 2. Apply to active session via sessions.configure RPC
        session_key = f"agent:{agent_id}:main"
        try:
            result = await self.gateway._request("sessions.configure", {
                "sessionKey": session_key,
                "model": full_model,
            })
            logger.info(f"Set gateway session model for {agent_id} to {full_model}: {result.get('ok', False)}")
        except Exception as e:
            logger.error(f"Failed to set gateway session model for {agent_id}: {e}")

        self._model_overrides[agent_id] = model
        self._save_model_overrides()

        # Apply immediately to in-memory state
        self.agents[agent_id].model = model
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
        
        logger.info("AgentRouter: Gateway event handlers registered")

    async def _handle_gateway_chat_event(self, frame: dict):
        """Handle chat events from Gateway - relay to Synapse clients.
        
        Gateway events are STATUS notifications, not content delivery.
        When state="final", we spawn a task to fetch the response (can't block listener).
        """
        payload = frame.get("payload", {})
        session_key = payload.get("sessionKey", "")
        run_id = payload.get("runId", "")
        state = payload.get("state", "")
        
        # Log chat events at debug level for diagnostics
        logger.debug(f"Chat event: state={state} session={session_key[:20] if session_key else 'none'}")
        
        # Spawn async task for final state to avoid deadlock with listener
        if state == "final":
            asyncio.create_task(self._handle_final_response(frame))
            return
        
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
            # Try to find by runId in active runs
            run_info = self._active_runs.get(run_id, {})
            agent_id = run_info.get("agent_id")
        
        if not agent_id:
            logger.debug(f"Chat event for unknown session: {session_key}")
            return
        
        logger.debug(f"Chat event for {agent_id}: state={state}, runId={run_id[:8] if run_id else 'none'}")
        
        # Handle delta events - stream text chunks to Synapse clients
        if state == "delta":
            msg = payload.get("message", {})
            delta_text = ""
            
            if isinstance(msg, dict):
                content = msg.get("content", "")
                # Content can be a string or an array of content blocks
                if isinstance(content, str):
                    delta_text = content
                elif isinstance(content, list):
                    # Extract text from content blocks [{'type': 'text', 'text': '...'}]
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            delta_text += block.get("text", "")
            else:
                delta_text = msg or payload.get("delta", payload.get("text", ""))
            
            if delta_text and isinstance(delta_text, str):
                await self._relay_chunk_to_subscribers(agent_id, delta_text, run_id)
            return
        
        # When run starts, update agent state
        if state == "started":
            # Run started - update agent state
            agent = self.agents.get(agent_id)
            if agent:
                agent.state = AgentState.WORKING
                agent.last_activity = datetime.now()

    async def _relay_chunk_to_subscribers(self, agent_id: str, delta_text: str, run_id: str):
        """Relay streaming text chunk to subscribed Synapse clients."""
        subscribers = self.manager.get_subscribers_for_agent(agent_id)
        if not subscribers:
            return
        
        logger.debug(f"Chunk: {len(delta_text)} chars to {len(subscribers)} subscribers for {agent_id}")
        
        chunk_frame = {
            "type": "chunk",
            "agentId": agent_id,
            "payload": {
                "text": delta_text,
                "runId": run_id
            }
        }
        
        for client_id in subscribers:
            try:
                await self.manager.send_to_client(client_id, chunk_frame)
            except Exception as e:
                logger.debug(f"Failed to send chunk to {client_id[:8]}: {e}")

    async def _handle_final_response(self, frame: dict):
        """Fetch and relay final response (runs as separate task to avoid deadlock)."""
        payload = frame.get("payload", {})
        session_key = payload.get("sessionKey", "")
        run_id = payload.get("runId", "")
        
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
            run_info = self._active_runs.get(run_id, {})
            agent_id = run_info.get("agent_id")
        
        if not agent_id:
            logger.debug(f"Final event for unknown session: {session_key}")
            return
        
        subscribers = self.manager.get_subscribers_for_agent(agent_id)
        
        # Fallback: if no subscribers, use client_id from _active_runs or broadcast
        run_info = self._active_runs.get(run_id, {})
        fallback_client = run_info.get("client_id")
        if not subscribers and fallback_client and fallback_client in self.manager.active_connections:
            subscribers = [fallback_client]
            logger.info(f"Final event for {agent_id}, using fallback client {fallback_client[:8]}")
        else:
            logger.info(f"Final event for {agent_id}, {len(subscribers)} subscribers")
        
        agent = self.agents.get(agent_id)
        fetch_session_key = agent.session_key if agent else session_key
        
        try:
            messages = await self.gateway.get_history(fetch_session_key, limit=5)
            logger.info(f"Fetched {len(messages)} messages from history")
            
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    raw_content = msg.get("content", msg.get("text", ""))
                    text = self._extract_message_text(raw_content)
                    ts = msg.get("ts", datetime.now().isoformat())
                    
                    # Skip internal/system messages (heartbeats, cron prompts, NO_REPLY, etc.)
                    if self._is_internal_message(text):
                        logger.debug(f"Skipping internal message for {agent_id}")
                        continue
                    
                    message_frame = {
                        "type": "message",
                        "agentId": agent_id,
                        "ts": ts,
                        "payload": {"role": "assistant", "text": text, "runId": run_id}
                    }
                    
                    if subscribers:
                        for subscriber_id in subscribers:
                            await self.manager.send_to_client(subscriber_id, message_frame)
                    else:
                        # No subscribers — drop the message, don't broadcast noise
                        logger.debug(f"No subscribers for {agent_id}, dropping message")
                    
                    logger.info(f"Relayed response for {agent_id} ({len(text)} chars)")
                    break
            else:
                logger.warning(f"No assistant message found for {agent_id}")
                
        except Exception as e:
            logger.error(f"Failed to fetch response for {agent_id}: {type(e).__name__}: {e}")
        
        # Update agent state
        if agent:
            agent.state = AgentState.IDLE
            agent.task = None
            agent.last_activity = datetime.now()
        
        if run_id in self._active_runs:
            del self._active_runs[run_id]

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
        
        # Broadcast status update
        await self.manager.broadcast({
            "type": "status",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": agent.to_dict()
        })

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

        _, _, _, model_display_names = self._load_models_from_config()

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
                    # Model display name from gateway config alias map
                    raw_model = sess["model"]
                    display_name = model_display_names.get(raw_model)
                    if display_name:
                        agent.model = display_name
                    else:
                        agent.model = raw_model.split("/")[-1] if "/" in raw_model else raw_model
                # Apply local model override if set
                if agent_id in self._model_overrides:
                    agent.model = self._model_overrides[agent_id]

        await self._broadcast_all_status()

    async def _update_agent_statuses_from_file(self):
        """Fallback: read status from agent_status.json (cron-updated)."""
        status_file = os.path.join(os.path.dirname(__file__), "data", "agent_status.json")

        try:
            if not os.path.exists(status_file):
                return

            with open(status_file, 'r') as f:
                data = json.load(f)

            for agent_data in data.get("agents", []):
                agent_id = agent_data.get("id")
                if agent_id in self.agents:
                    agent = self.agents[agent_id]
                    state_map = {
                        "idle": AgentState.IDLE,
                        "active": AgentState.WORKING,
                        "working": AgentState.WORKING,
                        "blocked": AgentState.BLOCKED,
                        "error": AgentState.ERROR,
                    }
                    agent.context_pct = agent_data.get("context_pct", 0)
                    agent.state = state_map.get(agent_data.get("status", "idle"), AgentState.IDLE)
                    agent.session_key = agent_data.get("session_key", agent.session_key)
                    agent.model = agent_data.get("model", agent.model).replace("claude-", "").replace("-4-5", "").replace("-4", "")
                    # Apply local model override if set
                    if agent_id in self._model_overrides:
                        agent.model = self._model_overrides[agent_id]
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
                "agents": [agent.to_dict() for agent in self.agents.values()]
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
                "agents": [agent.to_dict() for agent in self.agents.values()]
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
        text = payload.get("text", "")
        if not text:
            return {"type": "error", "payload": {"error": "Empty message"}}

        agent = self.agents.get(agent_id)
        if not agent:
            return {"type": "error", "payload": {"error": f"Unknown agent: {agent_id}"}}

        # Update agent state
        agent.state = AgentState.WORKING
        agent.task = text[:50]
        agent.last_activity = datetime.now()

        await self.manager.broadcast({
            "type": "status",
            "agentId": agent_id,
            "ts": datetime.now().isoformat(),
            "payload": agent.to_dict()
        })

        # Forward via Gateway WebSocket RPC
        # Note: chat.send returns immediately with {runId, status: "started"}
        # Actual response comes via Gateway 'chat' events (handled by _setup_gateway_event_handlers)
        # Model overrides are set via session_status, not per-message
        
        try:
            result = await self.gateway.send_message(agent.session_key, text)
            run_id = result.get("payload", {}).get("runId", "")
            
            # Track this run so we can route responses back
            if run_id:
                self._active_runs[run_id] = {
                    "agent_id": agent_id,
                    "client_id": client_id,
                    "started_at": datetime.now().isoformat()
                }

            return {"type": "ack", "agentId": agent_id, "payload": {"sent": True, "runId": run_id}}

        except Exception as e:
            agent.state = AgentState.ERROR
            logger.error(f"Failed to send message to {agent_id}: {e}")
            return {"type": "error", "payload": {"error": str(e)}}

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
            return {"type": "error", "payload": {"error": "Agent ID required"}}
        
        model = payload.get("model")
        if not model:
            return {"type": "error", "payload": {"error": "Model required"}}
        
        try:
            result = await self.set_agent_model(agent_id, model)
            if not result.get("ok", False):
                return {"type": "error", "payload": {"error": result.get("error", "Failed to set model")}}
            
            # Broadcast updated status to all clients
            agent = self.agents.get(agent_id)
            if agent:
                agent.model = model
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
                "payload": {"model": model, "success": True}
            }
        except Exception as e:
            logger.error(f"Failed to set model for {agent_id}: {e}")
            return {"type": "error", "payload": {"error": str(e)}}

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
        if isinstance(content, str):
            # Check if it looks like tool output (starts with common patterns)
            if content.strip().startswith(("```", "Successfully", "(no output)", "Command")):
                # Might be tool output that leaked through - skip short tool outputs
                if len(content) < 100:
                    return ""
            return content
        
        if isinstance(content, list):
            # Extract just the 'text' type blocks, ignore everything else
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    # Only include plain text blocks
                    if block_type == "text":
                        text = block.get("text", "")
                        # Skip if it looks like tool output marker
                        if text and not text.strip().startswith(("```", "(no output)")):
                            text_parts.append(text)
                    # Explicitly skip: thinking, toolCall, toolResult, tool_use, tool_result
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)
        
        return str(content) if content else ""

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
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if not os.path.exists(config_path):
        logger.warning(f"openclaw.json not found at {config_path}")
        return
    with open(config_path, "r") as f:
        data = json.load(f)
    default_ws = data.get("agents", {}).get("defaults", {}).get("workspace", "")
    for agent in data.get("agents", {}).get("list", []):
        aid = agent.get("id")
        if aid:
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
