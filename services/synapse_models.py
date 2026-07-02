"""Synapse model catalog helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


_CLOUD_DISPLAY_NAMES = {
    "anthropic/claude-opus-4-5": "Claude Opus 4.5",
    "anthropic/claude-opus-4-6": "Claude Opus 4.6",
    "anthropic/claude-sonnet-4-20250514": "Claude Sonnet 4",
    "anthropic/claude-sonnet-4-6": "Claude Sonnet 4.6",
    "google/gemini-2.5-pro": "Gemini 2.5 Pro",
    "google/gemini-2.5-flash": "Gemini 2.5 Flash",
    "google/gemini-3-pro": "Gemini 3 Pro",
    "google/gemini-3-pro-preview": "Gemini 3 Pro Preview",
    "google/gemini-3-flash": "Gemini 3 Flash",
    "openai-codex/gpt-5.4": "GPT-5.4 Codex",
    "openai-codex/gpt-5.5": "GPT-5.5 Codex",
    "openai/gpt-5.5": "GPT-5.5 Codex",
}

_BLOCKED_MODELS = {
    "local/local-fast": "Context window is too short for Synapse agent sessions.",
}
_BLOCKED_MODEL_INPUTS = set(_BLOCKED_MODELS) | {"local-fast"}


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    alias: str = ""
    short_id: str = ""
    context_window: int = 0  # 0 = unknown


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[ModelOption, ...]
    canonical_by_input: dict[str, str]
    display_by_id: dict[str, str]
    presets: dict[str, str]
    config_path: str
    error: Optional[str] = None

    def resolve(self, model: str) -> str:
        value = str(model or "").strip()
        if not value:
            return ""
        if value in _BLOCKED_MODEL_INPUTS or value.lower() in _BLOCKED_MODEL_INPUTS:
            return ""
        return self.canonical_by_input.get(value) or self.canonical_by_input.get(value.lower()) or value

    def context_window_for(self, model: str) -> int:
        """Return the configured context window for a model id/alias (0 = unknown)."""
        resolved = self.resolve(model)
        for option in self.models:
            if option.id == resolved:
                return option.context_window
        return 0

    def to_api_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "models": [
                {
                    "id": model.id,
                    "fullId": model.id,
                    "label": model.label,
                    "alias": model.alias,
                    "shortId": model.short_id,
                    "contextWindow": model.context_window,
                }
                for model in self.models
            ],
            "presets": dict(self.presets),
            "blockedModels": dict(_BLOCKED_MODELS),
            "fallback": bool(self.error),
            "error": self.error,
        }


def get_model_catalog() -> ModelCatalog:
    config_path = _openclaw_config_path()
    try:
        config = _read_config(config_path)
        raw_models = config.get("agents", {}).get("defaults", {}).get("models", {})
        if not isinstance(raw_models, dict):
            raise ValueError("agents.defaults.models is missing")
        return _build_catalog(raw_models, config, str(config_path))
    except Exception as exc:
        return _empty_catalog(str(config_path), str(exc))


def get_agent_model_defaults(agent_ids: Iterable[str]) -> dict[str, str]:
    config_path = _openclaw_config_path()
    try:
        config = _read_config(config_path)
    except Exception:
        return {}
    catalog = get_model_catalog()
    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        return {}
    defaults = agents.get("defaults", {})
    fallback = _model_ref(defaults.get("model") if isinstance(defaults, dict) else None)
    configured = _configured_agent_models(agents.get("list"))
    defaults: dict[str, str] = {}
    for agent_id in agent_ids:
        resolved = catalog.resolve(configured.get(agent_id) or fallback)
        if resolved:
            defaults[agent_id] = resolved
    return defaults


def _openclaw_config_path() -> Path:
    home = Path(os.environ.get("OPENCLAW_HOME", "~/.openclaw")).expanduser()
    for name in ("openclaw.json", "moltbot.json"):
        path = home / name
        if path.exists():
            return path
    return home / "openclaw.json"


def _read_config(config_path: Path) -> dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def _configured_agent_models(raw_agents: Any) -> dict[str, str]:
    if isinstance(raw_agents, list):
        return _configured_agent_models_from_list(raw_agents)
    if isinstance(raw_agents, dict):
        return _configured_agent_models_from_dict(raw_agents)
    return {}


def _configured_agent_models_from_list(raw_agents: list[Any]) -> dict[str, str]:
    models: dict[str, str] = {}
    for row in raw_agents:
        if not isinstance(row, dict):
            continue
        agent_id = str(row.get("id") or "").strip()
        model = _model_ref(row.get("model"))
        if agent_id and model:
            models[agent_id] = model
    return models


def _configured_agent_models_from_dict(raw_agents: dict[str, Any]) -> dict[str, str]:
    models: dict[str, str] = {}
    for agent_id, row in raw_agents.items():
        if not isinstance(row, dict):
            continue
        model = _model_ref(row.get("model"))
        if model:
            models[str(agent_id)] = model
    return models


def _model_ref(raw_model: Any) -> str:
    if isinstance(raw_model, str):
        return raw_model.strip()
    if isinstance(raw_model, dict):
        return str(raw_model.get("primary") or "").strip()
    return ""


def _build_catalog(raw_models: dict[str, Any], config: dict[str, Any], config_path: str) -> ModelCatalog:
    provider_names = _provider_model_names(config)
    provider_windows = _provider_context_windows(config)
    entries = [
        _model_option(model_id, info, provider_names, provider_windows)
        for model_id, info in raw_models.items()
        if model_id not in _BLOCKED_MODELS
    ]
    entries = sorted(entries, key=lambda model: (model.label.lower(), model.id.lower()))
    canonical = _input_map(entries)
    display = {model.id: model.label for model in entries}
    return ModelCatalog(tuple(entries), canonical, display, _infer_presets(entries), config_path)


def _model_option(
    model_id: str,
    info: Any,
    provider_names: dict[str, str],
    provider_windows: Optional[dict[str, int]] = None,
) -> ModelOption:
    data = info if isinstance(info, dict) else {}
    alias = str(data.get("alias") or "").strip()
    short_id = model_id.split("/", 1)[1] if "/" in model_id else model_id
    label = provider_names.get(model_id) or _CLOUD_DISPLAY_NAMES.get(model_id)
    if not label:
        label = alias.replace("-", " ").title() if alias else short_id.replace("-", " ").title()
    window = int(data.get("contextWindow") or (provider_windows or {}).get(model_id) or 0)
    return ModelOption(model_id, label, alias, short_id, window)


def _provider_model_names(config: dict[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    providers = config.get("models", {}).get("providers", {})
    if not isinstance(providers, dict):
        return names
    for provider, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        _add_provider_names(names, provider, provider_cfg.get("models", []))
    return names


def _add_provider_names(names: dict[str, str], provider: str, models: Any) -> None:
    if not isinstance(models, list):
        return
    for row in models:
        if not isinstance(row, dict):
            continue
        short_id = str(row.get("id") or "").strip()
        label = str(row.get("name") or "").strip()
        if short_id and label:
            names[f"{provider}/{short_id}"] = label


def _provider_context_windows(config: dict[str, Any]) -> dict[str, int]:
    """Map ``provider/id`` → contextWindow from the provider model lists."""
    windows: dict[str, int] = {}
    providers = config.get("models", {}).get("providers", {})
    if not isinstance(providers, dict):
        return windows
    for provider, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        models = provider_cfg.get("models", [])
        if not isinstance(models, list):
            continue
        for row in models:
            if not isinstance(row, dict):
                continue
            short_id = str(row.get("id") or "").strip()
            window = row.get("contextWindow")
            if short_id and isinstance(window, (int, float)) and window > 0:
                windows[f"{provider}/{short_id}"] = int(window)
    return windows


def _input_map(models: list[ModelOption]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for model in models:
        for key in (model.id, model.short_id, model.alias):
            _register_input(mapping, ambiguous, key, model.id)
    return mapping


def _register_input(mapping: dict[str, str], ambiguous: set[str], key: str, model_id: str) -> None:
    value = str(key or "").strip()
    if not value:
        return
    for candidate in {value, value.lower()}:
        existing = mapping.get(candidate)
        if existing is None and candidate not in ambiguous:
            mapping[candidate] = model_id
        elif existing != model_id:
            mapping.pop(candidate, None)
            ambiguous.add(candidate)


def _infer_presets(models: list[ModelOption]) -> dict[str, str]:
    by_id = {model.id: model.id for model in models}
    codex = by_id.get("openai/gpt-5.5") or by_id.get("openai-codex/gpt-5.5") or ""
    fast = codex or by_id.get("local/local-code") or by_id.get("local/local-27b-code") or ""
    balanced = codex or by_id.get("local/local-code") or by_id.get("local/local-27b-code") or fast
    deep = codex or by_id.get("local/local-research") or by_id.get("local/local-27b-research") or balanced
    return {"fast": fast, "balanced": balanced, "deep": deep}


def _empty_catalog(config_path: str, error: str) -> ModelCatalog:
    return ModelCatalog(
        models=tuple(),
        canonical_by_input={},
        display_by_id={},
        presets={"fast": "", "balanced": "", "deep": ""},
        config_path=config_path,
        error=error,
    )
