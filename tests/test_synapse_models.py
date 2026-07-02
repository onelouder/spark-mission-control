"""Synapse model catalog tests."""

import json

from services import synapse_models


def test_agent_model_defaults_resolve_from_openclaw_config(tmp_path, monkeypatch) -> None:
    config = {
        "agents": {
            "defaults": {
                "model": {"primary": "local-fast"},
                "models": {
                    "local/local-fast": {"alias": "local-fast"},
                    "openai-codex/gpt-5.5": {},
                },
            },
            "list": [
                {"id": "jarvis", "model": {"primary": "gpt-5.5"}},
                {"id": "aria", "model": "local/local-fast"},
            ],
        }
    }
    (tmp_path / "openclaw.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))

    defaults = synapse_models.get_agent_model_defaults(("jarvis", "aria", "dewey"))

    assert defaults == {"jarvis": "openai-codex/gpt-5.5"}


def test_model_catalog_blocks_local_fast(tmp_path, monkeypatch) -> None:
    config = {
        "agents": {
            "defaults": {
                "models": {
                    "local/local-fast": {"alias": "local-fast"},
                    "local/local-code": {"alias": "local-code"},
                    "openai/gpt-5.5": {"alias": "codex"},
                },
            },
        }
    }
    (tmp_path / "openclaw.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))

    catalog = synapse_models.get_model_catalog()
    payload = catalog.to_api_payload()

    model_ids = {model["id"] for model in payload["models"]}
    assert "local/local-fast" not in model_ids
    assert catalog.resolve("local-fast") == ""
    assert catalog.resolve("local/local-fast") == ""
    assert payload["blockedModels"] == {
        "local/local-fast": "Context window is too short for Synapse agent sessions.",
    }
    assert payload["presets"] == {
        "fast": "openai/gpt-5.5",
        "balanced": "openai/gpt-5.5",
        "deep": "openai/gpt-5.5",
    }
