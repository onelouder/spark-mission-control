"""Unit tests for the shared Synapse hub (services/synapse_hub.py)."""

from __future__ import annotations

import asyncio

import pytest

from services import openclaw_client, synapse_hub
from services.synapse_hub import (
    CLIENT_QUEUE_MAXSIZE,
    ConnectionManager,
    SynapseHub,
    _ClientChannel,
)


class FakeWebSocket:
    """Captures sent frames; can be told to stall to simulate a slow client."""

    def __init__(self, *, stall: bool = False) -> None:
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False
        self.stall_event = asyncio.Event()
        self.stall = stall

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, frame: dict) -> None:
        if self.stall:
            await self.stall_event.wait()
        self.sent.append(frame)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_hub_start_is_noop_offline(monkeypatch) -> None:
    """With no gateway URL configured, start() must spawn nothing."""
    monkeypatch.setenv(openclaw_client.GATEWAY_WS_URL_ENV, "")
    hub = SynapseHub()
    await hub.start()
    assert hub._running is False
    assert hub._status_task is None
    assert hub.gateway._supervisor_task is None
    await hub.stop()  # must be safe when never started


@pytest.mark.asyncio
async def test_chunks_coalesce_for_slow_client() -> None:
    """A stalled client's queued chunks for one run merge losslessly."""
    ws = FakeWebSocket(stall=True)
    chan = _ClientChannel("client-a", ws)
    chunk = lambda text: {  # noqa: E731
        "type": "chunk",
        "agentId": "jarvis",
        "ts": "t",
        "payload": {"text": text, "runId": "run-1"},
    }
    chan.offer(chunk("hel"))
    await asyncio.sleep(0)  # sender dequeues the first frame and stalls on it
    chan.offer(chunk("lo "))
    chan.offer(chunk("world"))
    assert chan.queue.qsize() == 1  # second+third coalesced into one frame
    ws.stall_event.set()
    await asyncio.sleep(0.01)
    assert [f["payload"]["text"] for f in ws.sent] == ["hel", "lo world"]
    chan.shutdown()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_status_frames_replace_latest_wins() -> None:
    ws = FakeWebSocket(stall=True)
    chan = _ClientChannel("client-a", ws)
    status = lambda pct: {  # noqa: E731
        "type": "status",
        "agentId": "jarvis",
        "ts": "t",
        "payload": {"agentId": "jarvis", "contextPct": pct},
    }
    chan.offer(status(1))
    await asyncio.sleep(0)  # sender holds frame 1
    chan.offer(status(2))
    chan.offer(status(3))
    assert chan.queue.qsize() == 1
    ws.stall_event.set()
    await asyncio.sleep(0.01)
    assert [f["payload"]["contextPct"] for f in ws.sent] == [1, 3]
    chan.shutdown()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_wedged_client_is_closed_not_blocking() -> None:
    """Control frames never drop; a queue full of them closes the client."""
    ws = FakeWebSocket(stall=True)
    chan = _ClientChannel("client-a", ws)
    control = {"type": "message", "agentId": "jarvis", "ts": "t", "payload": {"text": "x"}}
    for _ in range(CLIENT_QUEUE_MAXSIZE + 2):
        chan.offer(dict(control))
    assert chan.closed is True
    await asyncio.sleep(0.01)
    assert ws.closed is True


@pytest.mark.asyncio
async def test_chunk_copies_are_per_client() -> None:
    """Coalescing one client's queue must not mutate another client's frames."""
    slow_ws = FakeWebSocket(stall=True)
    fast_ws = FakeWebSocket()
    slow = _ClientChannel("slow", slow_ws)
    fast = _ClientChannel("fast", fast_ws)
    frame = {
        "type": "chunk",
        "agentId": "jarvis",
        "ts": "t",
        "payload": {"text": "a", "runId": "run-1"},
    }
    slow.offer(frame)
    fast.offer(frame)
    await asyncio.sleep(0)  # slow sender dequeues + stalls; fast delivers
    follow_up = {
        "type": "chunk",
        "agentId": "jarvis",
        "ts": "t",
        "payload": {"text": "b", "runId": "run-1"},
    }
    slow.offer(follow_up)  # queued fresh on slow
    slow.offer({**follow_up, "payload": {"text": "c", "runId": "run-1"}})  # coalesces
    assert fast_ws.sent[0]["payload"]["text"] == "a"  # untouched by slow's merge
    slow_ws.stall_event.set()
    await asyncio.sleep(0.01)
    assert [f["payload"]["text"] for f in slow_ws.sent] == ["a", "bc"]
    slow.shutdown()
    fast.shutdown()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_subscriptions_survive_reconnect_and_stale_disconnect() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    await manager.connect("tab-1", first)
    manager.subscribe("tab-1", "jarvis")
    # Reconnect with a fresh socket under the same client id.
    second = FakeWebSocket()
    await manager.connect("tab-1", second)
    assert manager.get_subscribers_for_agent("jarvis") == ["tab-1"]
    # The stale socket's cleanup must not evict the fresh registration.
    manager.disconnect("tab-1", first)
    assert "tab-1" in manager.channels
    assert manager.get_subscribers_for_agent("jarvis") == ["tab-1"]
    # A genuine disconnect removes it.
    manager.disconnect("tab-1", second)
    assert manager.get_subscribers_for_agent("jarvis") == []
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_terminal_pops_run_and_dedupes_replay() -> None:
    hub = SynapseHub()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")
    hub._active_runs["run-1"] = {
        "agent_id": "jarvis",
        "client_id": "tab-1",
        "client_message_id": "m1",
        "acc_text": "streamed reply",
        "started_at": 0.0,
    }
    payload = {"state": "final", "runId": "run-1", "sessionKey": "agent:jarvis:main"}
    await hub._handle_terminal("jarvis", "run-1", "final", payload)
    await asyncio.sleep(0.01)
    messages = [f for f in ws.sent if f["type"] == "message"]
    assert len(messages) == 1
    assert messages[0]["payload"]["text"] == "streamed reply"
    assert "run-1" not in hub._active_runs
    # Gateway replays the same terminal after a reconnect: suppressed.
    await hub._handle_terminal("jarvis", "run-1", "final", payload)
    await asyncio.sleep(0.01)
    assert len([f for f in ws.sent if f["type"] == "message"]) == 1
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_delta_routes_by_session_key_without_run_state() -> None:
    """Chunks flow even when the hub never saw the run start (reconnect case)."""
    hub = SynapseHub()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")
    await hub._handle_chat_event(
        {
            "type": "event",
            "event": "chat",
            "payload": {
                "state": "delta",
                "runId": "run-unknown",
                "sessionKey": "agent:jarvis:main",
                "delta": "live text",
            },
        }
    )
    await asyncio.sleep(0.01)
    chunks = [f for f in ws.sent if f["type"] == "chunk"]
    assert len(chunks) == 1
    assert chunks[0]["payload"]["text"] == "live text"
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cron_session_chat_is_not_relayed_to_panes() -> None:
    """Cron/voice runs share the agent prefix but must not flood the chat."""
    hub = SynapseHub()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")
    for session_key in (
        "agent:jarvis:cron:fcea6360:run:6888125d",
        "agent:jarvis:voice",
    ):
        await hub._handle_chat_event(
            {
                "type": "event",
                "event": "chat",
                "payload": {
                    "state": "delta",
                    "runId": "cron-run-1",
                    "sessionKey": session_key,
                    "deltaText": "cron noise",
                },
            }
        )
    await asyncio.sleep(0.01)
    assert [f for f in ws.sent if f["type"] in ("chunk", "message")] == []
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_voice_message_uses_explicit_session_key_and_pane_binding() -> None:
    hub = SynapseHub()
    requests = []

    class FakeGateway:
        async def request(self, method, params, *, timeout=30.0):
            requests.append((method, params))
            if method == "sessions.patch":
                return {"payload": {"model": params["model"]}}
            return {"payload": {"runId": "run-will", "status": "accepted"}}

    hub.gateway = FakeGateway()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")

    run_id, reply = await hub.send_voice_message(
        "tab-1",
        "1",
        "willb",
        "agent:willb:main",
        "hello",
        "turn-will",
        "openai-codex/gpt-5.5",
    )

    assert run_id == "run-will"
    assert requests == [
        (
            "sessions.patch",
            {"key": "agent:willb:main", "model": "openai-codex/gpt-5.5"},
        ),
        (
            "chat.send",
            {
                "sessionKey": "agent:willb:main",
                "message": "hello",
                "toolsAllow": ["memory_search", "memory_get", "session_status"],
                "idempotencyKey": "turn-will",
            },
        ),
    ]
    await asyncio.sleep(0.01)
    voice_frames = [frame for frame in ws.sent if frame["type"] == "voice_user"]
    assert voice_frames[0]["agentId"] == "willb"
    assert voice_frames[0]["paneId"] == "1"

    with pytest.raises(RuntimeError, match="sessionKey does not match agentId"):
        await hub.send_voice_message(
            "tab-1", "0", "willb", "agent:jarvis:main", "bad", "turn-bad"
        )

    await hub._handle_chat_event(
        {
            "type": "event",
            "event": "chat",
            "payload": {
                "state": "delta",
                "runId": "run-will",
                "sessionKey": "agent:jarvis:main",
                "deltaText": "Will ",
            },
        }
    )
    await hub._handle_chat_event(
        {
            "type": "event",
            "event": "chat",
            "payload": {
                "state": "final",
                "runId": "run-will",
                "sessionKey": "agent:jarvis:main",
                "message": "Will reply",
            },
        }
    )
    await asyncio.sleep(0.01)

    routed = [frame for frame in ws.sent if frame["type"] in {"chunk", "message"}]
    assert [(frame["type"], frame["agentId"], frame["paneId"]) for frame in routed] == [
        ("chunk", "willb", "1"),
        ("message", "willb", "1"),
    ]
    assert await reply == "Will reply"
    assert not [frame for frame in routed if frame["agentId"] == "jarvis"]

    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_message_patches_configured_default_before_chat_send(monkeypatch) -> None:
    class FakeCatalog:
        models = ()

        def resolve(self, model: str) -> str:
            return model

    monkeypatch.setattr(synapse_hub.synapse_models, "get_model_catalog", lambda: FakeCatalog())
    monkeypatch.setattr(
        synapse_hub.synapse_models,
        "get_agent_model_defaults",
        lambda agent_ids: {"atlas": "openai-codex/gpt-5.5"},
    )
    hub = SynapseHub()
    requests = []

    class FakeGateway:
        async def request(self, method, params, *, timeout=30.0):
            requests.append((method, params))
            if method == "sessions.patch":
                return {"payload": {"model": params["model"]}}
            return {"payload": {"runId": "run-atlas", "status": "accepted"}}

    hub.gateway = FakeGateway()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)

    await hub._handle_message("tab-1", "atlas", {"text": "hello", "clientMessageId": "m1"})
    await asyncio.sleep(0.01)

    assert requests == [
        (
            "sessions.patch",
            {"key": "agent:atlas:main", "model": "openai-codex/gpt-5.5"},
        ),
        (
            "chat.send",
            {
                "sessionKey": "agent:atlas:main",
                "message": "hello",
                "idempotencyKey": "m1",
            },
        ),
    ]
    assert [frame for frame in ws.sent if frame["type"] == "ack"]
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_orphan_runs_are_reaped() -> None:
    hub = SynapseHub()
    hub._active_runs["old"] = {"agent_id": "jarvis", "started_at": 0.0}
    hub._reap_orphan_runs()
    assert hub._active_runs == {}


@pytest.mark.asyncio
async def test_quiet_runs_emit_heartbeat_not_error() -> None:
    hub = SynapseHub()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")
    started_at = synapse_hub.time.monotonic() - 50
    hub._active_runs["run-1"] = {
        "agent_id": "jarvis",
        "client_id": "tab-1",
        "client_message_id": "m1",
        "acc_text": "",
        "started_at": started_at,
        "last_output_at": started_at,
    }

    hub._reap_orphan_runs()
    await asyncio.sleep(0.01)

    heartbeats = [frame for frame in ws.sent if frame["type"] == "run_heartbeat"]
    errors = [frame for frame in ws.sent if frame["type"] == "error"]
    assert heartbeats
    assert not errors
    assert heartbeats[0]["payload"]["runId"] == "run-1"
    assert heartbeats[0]["payload"]["status"] == "thinking"
    assert "run-1" in hub._active_runs
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_reset_aborts_active_run_first() -> None:
    """Reset = chat.abort, drop tracked runs, sessions.reset, resync."""
    hub = SynapseHub()
    calls = []

    class FakeGateway:
        is_connected = True

        async def request(self, method, params, *, timeout=30.0):
            calls.append(method)
            if method == "chat.history":
                return {"payload": {"messages": []}}
            return {"payload": {"ok": True}}

    hub.gateway = FakeGateway()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub.manager.subscribe("tab-1", "jarvis")
    hub._active_runs["run-1"] = {"agent_id": "jarvis", "started_at": 0.0}
    hub._last_delivered_text["jarvis"] = "stale"
    await hub._handle_reset("tab-1", "jarvis")
    await asyncio.sleep(0.01)
    assert calls[:2] == ["chat.abort", "sessions.reset"]
    assert "run-1" not in hub._active_runs
    assert "jarvis" not in hub._last_delivered_text
    types = [f["type"] for f in ws.sent]
    assert "reset" in types and "history" in types and "status" in types
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_reset_reports_abort_failure_without_resetting() -> None:
    hub = SynapseHub()
    calls = []

    class FakeGateway:
        is_connected = True

        async def request(self, method, params, *, timeout=30.0):
            calls.append(method)
            if method == "chat.abort":
                raise RuntimeError("locked run")
            return {"payload": {"ok": True}}

    hub.gateway = FakeGateway()
    ws = FakeWebSocket()
    await hub.manager.connect("tab-1", ws)
    hub._active_runs["run-1"] = {"agent_id": "jarvis", "started_at": 0.0}

    await hub._handle_reset("tab-1", "jarvis")
    await asyncio.sleep(0.01)

    assert calls == ["chat.abort"]
    assert "run-1" in hub._active_runs
    errors = [frame for frame in ws.sent if frame["type"] == "error"]
    assert errors
    assert "chat.abort failed: locked run" in errors[0]["payload"]["error"]
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_sessions_list_is_cached_and_single_flight() -> None:
    """One gateway call serves poll + connects within the TTL window."""
    hub = SynapseHub()
    calls = 0

    class FakeGateway:
        is_connected = True

        async def request(self, method, params, *, timeout=30.0):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return {"payload": {"sessions": [{"key": "agent:jarvis:main", "totalTokens": 7}]}}

    hub.gateway = FakeGateway()
    results = await asyncio.gather(*(hub._cached_sessions() for _ in range(5)))
    assert calls == 1  # single-flight: concurrent callers share one request
    assert all(r and r[0]["totalTokens"] == 7 for r in results)
    assert await hub._cached_sessions() is results[0]  # TTL hit
    assert calls == 1


@pytest.mark.asyncio
async def test_connect_rate_guard_rejects_storms() -> None:
    hub = SynapseHub()
    sockets = []
    for _ in range(synapse_hub.CONNECT_RATE_LIMIT + 5):
        ws = FakeWebSocket()
        sockets.append(ws)
        await hub.handle_connect("stormy-tab", ws)
    # The early connects register; the ones past the limit are closed unaccepted.
    rejected = [ws for ws in sockets if ws.closed and not ws.accepted]
    assert len(rejected) == 5
    hub.manager.shutdown_all()
    await asyncio.sleep(0)


def test_merge_session_keeps_config_default_over_runtime_model(monkeypatch) -> None:
    windows = {"openai-codex/gpt-5.5": 400000, "local/local-fast": 32768}
    monkeypatch.setattr(synapse_hub, "_model_context_window", lambda model: windows.get(model, 0))
    row = synapse_hub._base_agent("atlas", {"atlas": "openai-codex/gpt-5.5"})

    synapse_hub._merge_session(
        row,
        {
            "key": "agent:atlas:main",
            "modelProvider": "local",
            "model": "local-fast",
            "contextTokens": 32768,
        },
    )

    assert row["model"] == "openai-codex/gpt-5.5"
    assert row["defaultModel"] == "openai-codex/gpt-5.5"
    assert row["sessionModel"] == "local/local-fast"
    assert row["contextMax"] == 400000


def test_merge_session_resolves_model_context_window(monkeypatch) -> None:
    """Sessions without an explicit window use the model's configured window."""
    monkeypatch.setattr(synapse_hub, "_model_context_window", lambda model: 262144)
    row = synapse_hub._base_agent("jarvis")
    synapse_hub._merge_session(row, {"key": "agent:jarvis:main", "totalTokens": 262144})
    assert row["contextMax"] == 262144
    assert row["contextPct"] == 100.0


def test_merge_session_does_not_treat_context_window_as_used_tokens(monkeypatch) -> None:
    """contextTokens is capacity metadata, not usage."""
    monkeypatch.setattr(synapse_hub, "_model_context_window", lambda model: 262144)
    row = synapse_hub._base_agent("jarvis")
    synapse_hub._merge_session(row, {"key": "agent:jarvis:main", "contextTokens": 262144})
    assert row["contextMax"] == 262144
    assert row["contextUsed"] == 0
    assert row["contextPct"] == 0.0


def test_merge_session_estimates_usage_from_session_file_when_usage_missing(tmp_path, monkeypatch) -> None:
    """Local endpoints often report no token usage; keep a small file-size fallback."""
    monkeypatch.setattr(synapse_hub, "_model_context_window", lambda model: 262144)
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("x" * 400, encoding="utf-8")
    row = synapse_hub._base_agent("jarvis")
    synapse_hub._merge_session(
        row,
        {
            "key": "agent:jarvis:main",
            "contextTokens": 262144,
            "sessionFile": str(session_file),
        },
    )
    assert row["contextMax"] == 262144
    assert row["contextUsed"] == 100
    assert row["contextPct"] == 0.04


def test_merge_session_prefers_model_window_over_stale_session_context(monkeypatch) -> None:
    """A selected long-context model should not display an old 32k session cap."""
    windows = {"local/local-long": 262144}
    monkeypatch.setattr(synapse_hub, "_model_context_window", lambda model: windows.get(model, 0))
    row = synapse_hub._base_agent("jarvis")
    synapse_hub._merge_session(
        row,
        {
            "key": "agent:jarvis:main",
            "modelProvider": "local",
            "model": "local-long",
            "contextTokens": 32768,
            "contextPct": 100,
            "totalTokens": 32768,
        },
    )
    assert row["model"] == "local/local-long"
    assert row["contextMax"] == 262144
    assert row["contextPct"] == 12.5


@pytest.mark.asyncio
async def test_gateway_close_sentinel_unblocks_next_event() -> None:
    """next_event() must raise once the listener exits, not hang forever."""

    class _FakeSocket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration  # connection closed immediately

    conn = openclaw_client.GatewayConnection()
    conn.ws = _FakeSocket()
    await conn._listen()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(conn.next_event(), timeout=1.0)
    # Subsequent waiters also fail fast (sentinel is re-queued).
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(conn.next_event(), timeout=1.0)
