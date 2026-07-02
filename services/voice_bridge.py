"""Ether-Voice to OpenClaw bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import get_settings
from services import openclaw_client
from services.synapse_hub import HUB

try:  # pragma: no cover - optional runtime dependency
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VoiceBridgeRecord:
    """Runtime status for one attached Ether-Voice transport session."""

    id: str
    agent_id: str
    agent_name: str
    session_key: str
    voice: str
    model: str
    wake_phrases: list[str]
    public_url: str
    client_id: str = ""
    pane_id: str = ""
    state: str = "starting"
    error: str = ""
    service_session_id: str = ""
    last_user_text: str = ""
    last_turn_id: str = ""
    last_run_id: str = ""
    last_event_state: str = ""
    last_openclaw_error: str = ""
    last_assistant_text: str = ""
    say_count: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def mark(self, state: str, *, error: str = "", service_session_id: str = "") -> None:
        self.state = state
        self.error = error
        if service_session_id:
            self.service_session_id = service_session_id
        self.updated_at = _now()

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agentId": self.agent_id,
            "agentName": self.agent_name,
            "sessionKey": self.session_key,
            "paneId": self.pane_id,
            "voice": self.voice,
            "model": self.model,
            "wakePhrases": self.wake_phrases,
            "publicUrl": self.public_url,
            "clientId": self.client_id,
            "state": self.state,
            "error": self.error,
            "serviceSessionId": self.service_session_id,
            "lastUserText": self.last_user_text,
            "lastTurnId": self.last_turn_id,
            "lastRunId": self.last_run_id,
            "lastEventState": self.last_event_state,
            "lastOpenClawError": self.last_openclaw_error,
            "lastAssistantText": self.last_assistant_text,
            "sayCount": self.say_count,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class VoiceBridgeManager:
    """Starts and tracks active Ether-Voice bridge tasks."""

    def __init__(self) -> None:
        self._records: dict[str, VoiceBridgeRecord] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(
        self,
        agent_id: str,
        session_key: str,
        pane_id: str,
        model: str = "",
        client_id: str = "",
    ) -> VoiceBridgeRecord:
        self._validate(agent_id, session_key, pane_id, client_id)
        existing = self._live_for_binding(agent_id, session_key, pane_id, client_id)
        if existing is not None:
            if model:
                existing.model = model
            existing.updated_at = _now()
            return existing
        settings = get_settings()
        record = _record_for_agent(agent_id, session_key, pane_id, model, client_id)
        bridge = VoiceBridgeSession(record, settings.ether_voice_agent_ws_url)
        task = asyncio.create_task(bridge.run(), name=f"mc2-voice-{record.id}")
        task.add_done_callback(lambda done: self._finish(record.id, done))
        self._records[record.id] = record
        self._tasks[record.id] = task
        return record

    async def stop(self, session_id: str) -> VoiceBridgeRecord | None:
        task = self._tasks.pop(session_id, None)
        record = self._records.get(session_id)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if record is not None:
            record.mark("stopped")
        return record

    def list(self) -> list[VoiceBridgeRecord]:
        return list(self._records.values())

    def get(self, session_id: str) -> VoiceBridgeRecord | None:
        return self._records.get(session_id)

    def _live_for_binding(
        self, agent_id: str, session_key: str, pane_id: str, client_id: str
    ) -> VoiceBridgeRecord | None:
        terminal = {"stopped", "disconnected", "error"}
        normalized_session_key = session_key.strip()
        normalized_pane_id = pane_id.strip()
        normalized_client_id = client_id.strip()
        for record in reversed(list(self._records.values())):
            same_binding = (
                record.agent_id == agent_id
                and record.session_key == normalized_session_key
                and record.pane_id == normalized_pane_id
                and record.client_id == normalized_client_id
            )
            if same_binding and record.state not in terminal:
                return record
        return None

    def _validate(self, agent_id: str, session_key: str, pane_id: str, client_id: str) -> None:
        if agent_id not in openclaw_client.AGENT_REGISTRY:
            raise ValueError("Unknown agent")
        if not client_id.strip():
            raise ValueError("clientId is required")
        if not pane_id.strip():
            raise ValueError("paneId is required")
        if not session_key.strip():
            raise ValueError("sessionKey is required")
        if not _session_key_matches_agent(agent_id, session_key):
            raise ValueError("sessionKey does not match agentId")
        if websockets is None:
            raise RuntimeError("websockets package is not installed")
        if not get_settings().ether_voice_agent_ws_url:
            raise RuntimeError("ETHER_VOICE_AGENT_WS_URL is not configured")

    def _finish(self, session_id: str, task: asyncio.Task) -> None:
        self._tasks.pop(session_id, None)
        record = self._records.get(session_id)
        if record is None or record.state == "stopped":
            return
        if task.cancelled():
            record.mark("stopped")
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("voice bridge %s exited: %s", session_id, exc)
            record.mark("error", error=str(exc))
            return
        record.mark("disconnected")


class VoiceBridgeSession:
    """One northbound Ether-Voice agent client."""

    # Reconnect backoff bounds (seconds). The Ether-Voice appliance restarting
    # (deploy, crash, systemd restart) drops this WebSocket; without reconnect the
    # agent silently detaches and every audio session then dies at claim().
    RECONNECT_MIN_SECS = 1.0
    RECONNECT_MAX_SECS = 30.0

    def __init__(self, record: VoiceBridgeRecord, url: str) -> None:
        self.record = record
        self.url = url
        self.voice_ws = None
        self.seq = 1
        self.active_task: Optional[asyncio.Task] = None
        self.active_turn_id = ""
        self._backoff = self.RECONNECT_MIN_SECS

    async def run(self) -> None:
        """Keep an Ether-Voice agent attached, reconnecting on any drop.

        Only stops on cancellation (MANAGER.stop); a closed/failed WebSocket is
        retried with capped exponential backoff so the agent re-attaches after the
        appliance restarts.
        """
        try:
            while True:
                try:
                    await self._connect_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - surface + retry any drop
                    logger.warning(
                        "voice bridge %s connection error: %s", self.record.agent_id, exc
                    )
                    self.record.mark("reconnecting", error=str(exc))
                else:
                    # Stream ended cleanly (e.g. appliance closed the socket on restart).
                    self.record.mark("reconnecting")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, self.RECONNECT_MAX_SECS)
        finally:
            await self._cancel_active()
            self.voice_ws = None

    async def _connect_once(self) -> None:
        """One Ether-Voice attach: connect, hello/welcome, then pump events.

        Returns when the appliance closes the stream; raises on any connection
        failure. ``run`` decides whether to retry."""
        self.record.mark("connecting")
        async with websockets.connect(self.url, max_size=2**20) as ws:  # type: ignore[union-attr]
            self.voice_ws = ws
            self.seq = 1  # fresh appliance session -> per-direction seq restarts
            await ws.send(json.dumps(_hello(self.record)))
            await self._handle_welcome(json.loads(await ws.recv()))
            self._backoff = self.RECONNECT_MIN_SECS  # attached OK -> reset backoff
            try:
                async for raw in ws:
                    await self._handle_voice_event(json.loads(raw))
            finally:
                self.voice_ws = None

    async def _handle_welcome(self, event: dict[str, Any]) -> None:
        if event.get("type") == "error":
            raise RuntimeError(event.get("message") or "Ether-Voice rejected hello")
        if event.get("type") != "welcome":
            raise RuntimeError("Ether-Voice did not send welcome")
        accepted = event.get("accepted") if isinstance(event.get("accepted"), dict) else {}
        self.record.wake_phrases = [
            str(phrase) for phrase in accepted.get("wake_phrases", []) if str(phrase).strip()
        ]
        self.record.mark("waiting_audio", service_session_id=str(event.get("session_id") or ""))

    async def _handle_voice_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "user_turn":
            await self._start_turn(event)
            return
        if event_type == "barge_in":
            await self._barge_in()
            return
        if event_type == "error":
            self.record.mark("error", error=str(event.get("message") or "voice error"))

    async def _start_turn(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or "").strip()
        turn_id = str(event.get("turn_id") or uuid.uuid4().hex[:12])
        if not text:
            return
        self.record.last_user_text = text
        self.record.last_turn_id = turn_id
        self.record.last_openclaw_error = ""
        self.record.last_assistant_text = ""
        self.record.say_count = 0
        self.record.mark("heard")
        await self._cancel_active()
        self.active_turn_id = turn_id
        self.active_task = asyncio.create_task(self._run_turn(turn_id, text))

    async def _barge_in(self) -> None:
        await self._cancel_active()
        with suppress(Exception):
            await HUB.gateway.request(
                "chat.abort", {"sessionKey": self.record.session_key}, timeout=5.0
            )

    async def _cancel_active(self) -> None:
        if self.active_task is None or self.active_task.done():
            return
        self.active_task.cancel()
        with suppress(asyncio.CancelledError):
            await self.active_task

    async def _run_turn(self, turn_id: str, text: str) -> None:
        try:
            await self._stream_openclaw_turn(turn_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("voice turn failed for %s: %s", self.record.agent_id, exc)
            self.record.last_openclaw_error = str(exc)
            await self._say(turn_id, "Voice bridge could not reach OpenClaw.")
            await self._end_turn(turn_id)
            self.record.mark("waiting_audio")

    async def _stream_openclaw_turn(self, turn_id: str, text: str) -> None:
        self.record.mark("thinking")
        run_id, final_text = await HUB.send_voice_message(
            self.record.client_id,
            self.record.pane_id,
            self.record.agent_id,
            self.record.session_key,
            text,
            turn_id,
            self.record.model,
        )
        self.record.last_run_id = run_id
        try:
            reply = await asyncio.wait_for(final_text, timeout=90.0)
        except asyncio.CancelledError:
            self.record.last_event_state = "aborted"
            await self._end_turn(turn_id)
            self.record.mark("waiting_audio")
            return
        self.record.last_event_state = "final"
        if reply:
            await self._say(turn_id, str(reply))
        else:
            self.record.last_openclaw_error = "OpenClaw final event had no speakable text"
        await self._end_turn(turn_id)
        self.record.mark("waiting_audio")

    async def _say(self, turn_id: str, text: str) -> None:
        if self.voice_ws is None:
            return
        self.record.last_assistant_text = text.strip()
        self.record.say_count += 1
        self.record.updated_at = _now()
        self.seq += 1
        await self.voice_ws.send(
            json.dumps(
                {
                    "type": "say",
                    "seq": self.seq,
                    "session_id": self.record.service_session_id,
                    "turn_id": turn_id,
                    "text": text,
                }
            )
        )

    async def _end_turn(self, turn_id: str) -> None:
        if self.voice_ws is None:
            return
        self.seq += 1
        await self.voice_ws.send(
            json.dumps(
                {
                    "type": "end_of_turn",
                    "seq": self.seq,
                    "session_id": self.record.service_session_id,
                    "turn_id": turn_id,
                }
            )
        )

MANAGER = VoiceBridgeManager()


async def start(
    agent_id: str,
    session_key: str,
    pane_id: str,
    model: str = "",
    client_id: str = "",
) -> VoiceBridgeRecord:
    return await MANAGER.start(agent_id, session_key, pane_id, model, client_id)


async def stop(session_id: str) -> VoiceBridgeRecord | None:
    return await MANAGER.stop(session_id)


def list_sessions() -> list[VoiceBridgeRecord]:
    return MANAGER.list()


def get_session(session_id: str) -> VoiceBridgeRecord | None:
    return MANAGER.get(session_id)


def _record_for_agent(
    agent_id: str,
    session_key: str = "",
    pane_id: str = "",
    model: str = "",
    client_id: str = "",
) -> VoiceBridgeRecord:
    settings = get_settings()
    row = openclaw_client.AGENT_REGISTRY[agent_id]
    bound_session_key = session_key.strip() or _session_key(agent_id)
    return VoiceBridgeRecord(
        id=f"voice_{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        agent_name=row["name"],
        session_key=bound_session_key,
        pane_id=pane_id.strip(),
        voice=_voice_for_agent(agent_id),
        model=model.strip() or _model_for_agent(agent_id),
        wake_phrases=_wake_phrases(agent_id),
        public_url=_public_url_for_agent(settings.ether_voice_public_url, agent_id),
        client_id=client_id.strip(),
    )


def _voice_for_agent(agent_id: str) -> str:
    settings = get_settings()
    return _mapped_value(settings.ether_voice_agent_voices, agent_id) or settings.ether_voice_default_voice


def _model_for_agent(agent_id: str) -> str:
    settings = get_settings()
    return _mapped_value(settings.ether_voice_agent_models, agent_id) or settings.ether_voice_default_model


def _wake_phrases(agent_id: str) -> list[str]:
    settings = get_settings()
    mapped = _mapped_phrases(settings.ether_voice_agent_wake_phrases, agent_id)
    if mapped:
        return mapped
    configured = settings.ether_voice_wake_phrases
    return [phrase.strip() for phrase in configured.split(",") if phrase.strip()]


def _public_url_for_agent(base_url: str, agent_id: str) -> str:
    if not base_url:
        return ""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["agent"] = agent_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mapped_value(configured: str, agent_id: str) -> str:
    for item in configured.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() == agent_id:
            return value.strip()
    return ""


def _mapped_phrases(configured: str, agent_id: str) -> list[str]:
    for item in configured.split(";"):
        key, separator, value = item.partition("=")
        if separator and key.strip() == agent_id:
            return [phrase.strip() for phrase in value.split("|") if phrase.strip()]
    return []


def _hello(record: VoiceBridgeRecord) -> dict[str, Any]:
    return {
        "type": "hello",
        "seq": 1,
        "protocol_version": PROTOCOL_VERSION,
        "agent_name": record.agent_id,
        "auth": get_settings().ether_voice_agent_auth,
        "voice": record.voice,
        "wake_phrases": record.wake_phrases,
        "capabilities": {"barge_in": True, "text": True, "audio": False},
    }


def _event_text(payload: dict[str, Any]) -> str:
    for key in (
        "message",
        "content",
        "text",
        "delta",
        "deltaText",
        "assistantText",
        "assistantTexts",
        "output",
        "response",
        "result",
    ):
        text = openclaw_client.extract_message_text(payload.get(key))
        if text:
            return text
    return ""


def _session_key(agent_id: str) -> str:
    return openclaw_client.AGENT_REGISTRY[agent_id]["session_key"]


def _session_key_matches_agent(agent_id: str, session_key: str) -> bool:
    parts = session_key.strip().split(":")
    return len(parts) >= 2 and parts[0] == "agent" and parts[1] == agent_id


