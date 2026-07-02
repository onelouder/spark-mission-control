"""Synapse voice bridge API tests."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from services.voice_bridge import VoiceBridgeManager, VoiceBridgeRecord, VoiceBridgeSession, _event_text


@pytest.mark.asyncio
async def test_voice_start_rejects_unknown_agent(app_client: AsyncClient) -> None:
    response = await app_client.post(
        "/api/synapse/voice/sessions", json={"agentId": "no-such-agent"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown agent"


@pytest.mark.asyncio
async def test_voice_start_requires_configured_appliance(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import get_settings

    monkeypatch.setenv("ETHER_VOICE_AGENT_WS_URL", "")
    get_settings.cache_clear()

    response = await app_client.post(
        "/api/synapse/voice/sessions",
        json={
            "agentId": "jarvis",
            "clientId": "client-test",
            "paneId": "0",
            "sessionKey": "agent:jarvis:main",
        },
    )

    assert response.status_code == 503
    assert "ETHER_VOICE_AGENT_WS_URL" in response.json()["detail"]


@pytest.mark.asyncio
async def test_voice_start_returns_session_payload(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import voice_bridge

    async def _start(
        agent_id: str,
        session_key: str,
        pane_id: str,
        model: str = "",
        client_id: str = "",
    ) -> VoiceBridgeRecord:
        return VoiceBridgeRecord(
            id="voice_test",
            agent_id=agent_id,
            agent_name="Jarvis",
            session_key=session_key,
            voice="bm_daniel",
            model=model,
            wake_phrases=["jarvis"],
            public_url="https://voice.example.test",
            client_id=client_id,
            pane_id=pane_id,
            state="waiting_audio",
        )

    monkeypatch.setattr(voice_bridge, "start", _start)

    response = await app_client.post(
        "/api/synapse/voice/sessions",
        json={
            "agentId": "jarvis",
            "model": "local/local-fast",
            "clientId": "client-test",
            "paneId": "0",
            "sessionKey": "agent:jarvis:main",
        },
    )

    assert response.status_code == 200
    assert response.json()["session"]["agentId"] == "jarvis"
    assert response.json()["session"]["model"] == "local/local-fast"
    assert response.json()["session"]["publicUrl"] == "https://voice.example.test"
    assert response.json()["session"]["clientId"] == "client-test"
    assert response.json()["session"]["paneId"] == "0"
    assert response.json()["session"]["sessionKey"] == "agent:jarvis:main"


def test_voice_record_adds_agent_to_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_PUBLIC_URL", "https://voice.example.test/voice?gain=4")
    get_settings.cache_clear()

    record = voice_bridge._record_for_agent("jarvis", "agent:jarvis:main", "0")

    assert record.public_url == "https://voice.example.test/voice?gain=4&agent=jarvis"
    assert record.session_key == "agent:jarvis:main"


def test_voice_record_overrides_stale_agent_in_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_PUBLIC_URL", "https://voice.example.test/voice?agent=jarvis")
    get_settings.cache_clear()

    record = voice_bridge._record_for_agent("willb", "agent:willb:main", "0")

    assert record.public_url == "https://voice.example.test/voice?agent=willb"
    assert record.session_key == "agent:willb:main"


def test_voice_record_uses_per_agent_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_DEFAULT_VOICE", "bm_daniel")
    monkeypatch.setenv("ETHER_VOICE_AGENT_VOICES", "jarvis=bm_george,willb=af_heart")
    get_settings.cache_clear()

    assert voice_bridge._voice_for_agent("jarvis") == "bm_george"
    assert voice_bridge._voice_for_agent("willb") == "af_heart"
    assert voice_bridge._voice_for_agent("atlas") == "bm_daniel"


def test_voice_record_prefers_requested_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_DEFAULT_MODEL", "local/local-fast")
    get_settings.cache_clear()

    record = voice_bridge._record_for_agent(
        "jarvis", "agent:jarvis:main", "0", "openai-codex/gpt-5.5"
    )

    assert record.model == "openai-codex/gpt-5.5"


def test_voice_record_uses_per_agent_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_DEFAULT_MODEL", "local/local-fast")
    monkeypatch.setenv("ETHER_VOICE_AGENT_MODELS", "jarvis=local/local-code")
    get_settings.cache_clear()

    assert voice_bridge._model_for_agent("jarvis") == "local/local-code"
    assert voice_bridge._model_for_agent("willb") == "local/local-fast"


@pytest.mark.asyncio
async def test_voice_manager_reuses_only_exact_live_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import voice_bridge

    manager = VoiceBridgeManager()

    class FakeSession:
        def __init__(self, record: VoiceBridgeRecord, url: str) -> None:
            self.record = record
            self.url = url

        async def run(self) -> None:
            await asyncio.Event().wait()

    def fake_record(
        agent_id: str,
        session_key: str,
        pane_id: str,
        model: str = "",
        client_id: str = "",
    ) -> VoiceBridgeRecord:
        return VoiceBridgeRecord(
            id=f"voice_{agent_id}_{client_id or 'default'}_{pane_id}",
            agent_id=agent_id,
            agent_name="Will B.",
            session_key=session_key,
            voice="af_heart",
            model=model,
            wake_phrases=[],
            public_url="https://voice.example.test",
            client_id=client_id,
            pane_id=pane_id,
            state="waiting_audio",
        )

    monkeypatch.setattr(manager, "_validate", lambda *args: None)
    monkeypatch.setattr(voice_bridge, "VoiceBridgeSession", FakeSession)
    monkeypatch.setattr(voice_bridge, "_record_for_agent", fake_record)

    first = await manager.start(
        "willb", "agent:willb:main", "0", "local/local-fast", "client-1"
    )
    second = await manager.start(
        "willb", "agent:willb:main", "0", "local/local-code", "client-1"
    )
    third = await manager.start(
        "willb", "agent:willb:main", "1", "local/local-long", "client-1"
    )
    fourth = await manager.start(
        "jarvis", "agent:jarvis:main", "0", "local/local-fast", "client-1"
    )

    assert second is first
    assert third is not first
    assert fourth is not first
    assert first.model == "local/local-code"
    assert first.client_id == "client-1"
    assert third.model == "local/local-long"
    assert third.pane_id == "1"
    assert fourth.session_key == "agent:jarvis:main"
    assert len(manager.list()) == 3

    await manager.stop(first.id)
    await manager.stop(third.id)
    await manager.stop(fourth.id)



@pytest.mark.asyncio
async def test_voice_turn_routes_transcript_through_synapse_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = asyncio.get_running_loop().create_future()
    future.set_result("The active Synapse pane answered.")
    calls = []
    spoken = []
    ended = []

    class FakeHub:
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
            calls.append((client_id, pane_id, agent_id, session_key, text, client_message_id, model))
            return "run_voice", future

    record = VoiceBridgeRecord(
        id="voice_test",
        agent_id="jarvis",
        agent_name="Jarvis",
        session_key="agent:jarvis:main",
        voice="bm_daniel",
        model="local/local-fast",
        wake_phrases=[],
        public_url="https://voice.example.test",
        client_id="client-1",
        pane_id="0",
    )
    session = VoiceBridgeSession(record, "ws://voice.example.test")

    async def _say(turn_id: str, text: str) -> None:
        spoken.append((turn_id, text))

    async def _end_turn(turn_id: str) -> None:
        ended.append(turn_id)

    monkeypatch.setattr("services.voice_bridge.HUB", FakeHub())
    session._say = _say  # type: ignore[method-assign]
    session._end_turn = _end_turn  # type: ignore[method-assign]

    await session._stream_openclaw_turn("turn_test", "hello")

    assert calls == [
        (
            "client-1",
            "0",
            "jarvis",
            "agent:jarvis:main",
            "hello",
            "turn_test",
            "local/local-fast",
        )
    ]
    assert record.last_run_id == "run_voice"
    assert record.last_event_state == "final"
    assert spoken == [("turn_test", "The active Synapse pane answered.")]
    assert ended == ["turn_test"]
    assert record.state == "waiting_audio"


@pytest.mark.asyncio
async def test_voice_turn_records_empty_synapse_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = asyncio.get_running_loop().create_future()
    future.set_result("")
    spoken = []
    ended = []

    class FakeHub:
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
            return "run_voice", future

    record = VoiceBridgeRecord(
        id="voice_test",
        agent_id="jarvis",
        agent_name="Jarvis",
        session_key="agent:jarvis:main",
        voice="bm_daniel",
        model="local/local-fast",
        wake_phrases=[],
        public_url="https://voice.example.test",
        client_id="client-1",
        pane_id="0",
    )
    session = VoiceBridgeSession(record, "ws://voice.example.test")

    async def _say(turn_id: str, text: str) -> None:
        spoken.append((turn_id, text))

    async def _end_turn(turn_id: str) -> None:
        ended.append(turn_id)

    monkeypatch.setattr("services.voice_bridge.HUB", FakeHub())
    session._say = _say  # type: ignore[method-assign]
    session._end_turn = _end_turn  # type: ignore[method-assign]

    await session._stream_openclaw_turn("turn_test", "hello")

    assert spoken == []
    assert ended == ["turn_test"]
    assert record.last_openclaw_error == "OpenClaw final event had no speakable text"
    assert record.state == "waiting_audio"


def test_voice_record_uses_per_agent_wake_phrases(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_AGENT_WAKE_PHRASES", "jarvis=jarvis|hey jarvis;willb=will|hey will")
    get_settings.cache_clear()

    assert voice_bridge._wake_phrases("jarvis") == ["jarvis", "hey jarvis"]
    assert voice_bridge._wake_phrases("willb") == ["will", "hey will"]


def test_empty_wake_phrases_mean_always_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings
    from services import voice_bridge

    monkeypatch.setenv("ETHER_VOICE_WAKE_PHRASES", "")
    monkeypatch.setenv("ETHER_VOICE_AGENT_WAKE_PHRASES", "")
    get_settings.cache_clear()

    assert voice_bridge._wake_phrases("jarvis") == []


def test_voice_event_text_extracts_nested_openclaw_message() -> None:
    payload = {
        "state": "final",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Yes, I can hear you."}],
        },
    }

    assert _event_text(payload) == "Yes, I can hear you."


def test_voice_event_text_extracts_openclaw_assistant_texts() -> None:
    payload = {
        "state": "final",
        "assistantTexts": ["Yes, I can hear you from voice."],
    }

    assert _event_text(payload) == "Yes, I can hear you from voice."
