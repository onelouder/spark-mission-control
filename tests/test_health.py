"""Health endpoint smoke tests."""

import pytest
from httpx import AsyncClient

from api.routers import synapse


@pytest.mark.integration
async def test_health_returns_ok_when_services_up(app_client: AsyncClient) -> None:
    """``/api/health`` reports ``ok`` when Postgres + Redis are reachable."""
    response = await app_client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["postgres"] == "ok"
    assert payload["checks"]["redis"] == "ok"
    assert payload["checks"]["mission_control_v2"] == "ok"
    assert payload["checks"]["projectbox"] == "ok"
    assert payload["checks"]["openclaw"] in ("disabled", "ok", "down")


@pytest.mark.integration
async def test_root_serves_control_hub(app_client: AsyncClient) -> None:
    """``/`` returns the Mission Control hub (tasks → Project-Box)."""
    response = await app_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Mission Control" in body
    assert "Project-Box" in body
    assert "127.0.0.1:3200" in body
    assert "/legacy/kanban" not in body
    assert "/static/health-badge.js" in body


@pytest.mark.integration
async def test_legacy_kanban_is_removed(app_client: AsyncClient) -> None:
    """The deprecated Kanban template is no longer served."""
    response = await app_client.get("/legacy/kanban")
    assert response.status_code == 404


@pytest.mark.integration
async def test_kanban_redirects_to_projectbox(app_client: AsyncClient) -> None:
    """Old Kanban bookmarks redirect to Project-Box."""
    response = await app_client.get("/kanban", follow_redirects=False)
    assert response.status_code == 302
    assert "5173" in response.headers["location"]


@pytest.mark.integration
async def test_info_returns_app_metadata(app_client: AsyncClient) -> None:
    """``/api/info`` returns the application identity payload."""
    response = await app_client.get("/api/info")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "mission-control-v2"
    assert "/docs" in payload["docs"]
    assert payload["tasks"]["source"] == "projectbox"
    assert "api" in payload["tasks"]
    assert payload["crm"]["source"] == "twenty"
    assert "3200" in payload["crm"]["ui"]
    assert payload["crm"]["redirect"] == "/crm"
    surface_ids = {surface["id"] for surface in payload["surfaces"]}
    assert {
        "hub",
        "constellation",
        "synapse",
        "briefing",
        "email",
        "crm",
        "queue",
        "tasks",
    } <= surface_ids
    assert payload["constellation"]["api"] == "/api/openclaw/constellation"


@pytest.mark.integration
async def test_constellation_page_loads(app_client: AsyncClient) -> None:
    """``/constellation`` is the primary OpenClaw surface."""
    response = await app_client.get("/constellation")
    assert response.status_code == 200
    body = response.text
    assert "OpenClaw constellation" in body
    assert "/api/openclaw/constellation" in body
    assert 'href="/constellation"' in body


@pytest.mark.integration
async def test_synapse_page_loads_terminal(app_client: AsyncClient) -> None:
    """``/synapse`` serves the multi-agent terminal surface."""
    response = await app_client.get("/synapse")
    assert response.status_code == 200
    body = response.text
    assert "Synapse" in body
    assert 'id="synapse-grid"' in body
    assert 'id="synapse-sessions-overlay"' in body
    assert 'id="synapse-sessions"' in body
    assert "/static/synapse.js" in body
    assert 'href="/synapse"' in body


@pytest.mark.integration
async def test_queue_page_loads_board(app_client: AsyncClient) -> None:
    """``/queue`` serves the Agent Queue board."""
    response = await app_client.get("/queue")
    assert response.status_code == 200
    body = response.text
    assert "Agent queue" in body
    assert 'id="queue-board"' in body
    assert "/static/queue.js" in body
    assert 'href="/queue"' in body
    assert "placeholder.html" not in body


@pytest.mark.integration
async def test_constellation_api_returns_agents(app_client: AsyncClient) -> None:
    """Constellation API exposes gateway and registered agents."""
    response = await app_client.get("/api/openclaw/constellation")
    assert response.status_code == 200
    payload = response.json()
    assert "gateway" in payload
    assert "queue" in payload
    assert "config" in payload
    agent_ids = {agent["id"] for agent in payload["agents"]}
    assert "jarvis" in agent_ids


@pytest.mark.integration
async def test_synapse_fleet_returns_full_constellation(app_client: AsyncClient) -> None:
    """Synapse fleet API exposes the multi-agent constellation."""
    response = await app_client.get("/api/synapse/fleet")
    assert response.status_code == 200
    payload = response.json()
    agent_ids = {agent["agentId"] for agent in payload["agents"]}
    assert {"jarvis", "atlas", "dewey", "xavier"} <= agent_ids
    jarvis = next(agent for agent in payload["agents"] if agent["agentId"] == "jarvis")
    assert jarvis["contextUsed"] == 0
    # contextMax resolves from the agent's default model in the catalog
    # (falling back to 200k only when the window is unknown).
    from services import synapse_models

    defaults = synapse_models.get_agent_model_defaults(["jarvis"])
    expected = (
        synapse_models.get_model_catalog().context_window_for(defaults.get("jarvis", ""))
        or 200000
    )
    assert jarvis["contextMax"] == expected
    assert "gateway" in payload


def test_synapse_session_merge_exposes_token_usage() -> None:
    """Gateway session metadata includes pane-ready used/max token counts."""
    rows = [synapse._base_agent("jarvis")]
    merged = synapse._merge_sessions(
        rows,
        [
            {
                "key": "agent:jarvis:main",
                "state": "running",
                "totalTokens": 12345,
                "contextWindow": 200000,
            }
        ],
    )

    assert merged[0]["state"] == "working"
    assert merged[0]["contextUsed"] == 12345
    assert merged[0]["contextMax"] == 200000
    assert merged[0]["contextPct"] == 6.17


def test_synapse_session_merge_exposes_effective_model() -> None:
    """Gateway provider/model rows become model-picker ids."""
    rows = [synapse._base_agent("jarvis", {"jarvis": "local/local-fast"})]
    merged = synapse._merge_sessions(
        rows,
        [
            {
                "key": "agent:jarvis:main",
                "modelProvider": "openai-codex",
                "model": "gpt-5.5",
            }
        ],
    )

    assert merged[0]["model"] == "openai-codex/gpt-5.5"


@pytest.mark.integration
async def test_synapse_model_catalog_api(app_client: AsyncClient) -> None:
    """Synapse exposes the model picker catalog."""
    response = await app_client.get("/api/synapse/models")
    assert response.status_code == 200
    payload = response.json()
    assert "models" in payload
    assert "presets" in payload
    assert {"fast", "balanced", "deep"} <= set(payload["presets"])


@pytest.mark.integration
async def test_synapse_sessions_list_api(app_client: AsyncClient) -> None:
    """Synapse exposes session drawer data without blanking the UI offline."""
    response = await app_client.get("/api/sessions/list")
    assert response.status_code == 200
    payload = response.json()
    assert "sessions" in payload
    assert isinstance(payload["sessions"], list)


@pytest.mark.integration
async def test_crm_redirects_to_twenty(app_client: AsyncClient) -> None:
    """``/crm`` is a compatibility redirect to Twenty."""
    response = await app_client.get("/crm", follow_redirects=False)
    assert response.status_code == 302
    assert "127.0.0.1:3200" in response.headers["location"]


@pytest.mark.integration
async def test_app_bar_shows_crm_on_email_page(app_client: AsyncClient) -> None:
    """Wrapped apps stay visible in the shared app bar."""
    response = await app_client.get("/email")
    assert response.status_code == 200
    body = response.text
    assert 'href="http://127.0.0.1:3200"' in body
    assert 'target="_blank" rel="noopener"' in body
    assert ">CRM ↗<" in body


@pytest.mark.integration
async def test_brief_stub_is_removed(app_client: AsyncClient) -> None:
    """The old vendored Kanban briefing stub is gone."""
    response = await app_client.get("/api/brief")
    assert response.status_code == 404


@pytest.mark.integration
async def test_sync_stubs_are_removed(app_client: AsyncClient) -> None:
    """Legacy sync stubs are gone with the Kanban bundle."""
    email = await app_client.get("/api/sync/email")
    calendar = await app_client.get("/api/sync/calendar")
    assert email.status_code == 404
    assert calendar.status_code == 404


@pytest.mark.integration
async def test_static_assets_are_served(app_client: AsyncClient) -> None:
    """Static assets needed by the current UI are reachable."""
    for path in (
        "/static/mission-control.css",
        "/static/ide-noir.css",
        "/static/v2-overrides.css",
        "/static/health-badge.js",
        "/static/queue.js",
        "/static/synapse.js",
    ):
        response = await app_client.get(path)
        assert response.status_code == 200, f"missing static asset {path}"
