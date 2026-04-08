#!/usr/bin/env python3
"""Shared OpenClaw config and local LLM runtime helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

import httpx

DEFAULT_OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
CANONICAL_OPENCLAW_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "openclaw" / "configs" / "live-openclaw" / "openclaw.json"
)
OPENCLAW_BIN_DIR = "/home/jwells/.npm-global/bin"
PRIMARY_LLM_PROVIDER = os.environ.get("MISSION_CONTROL_INTERNAL_LLM_PROVIDER", "llamacpp").strip() or "llamacpp"

PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
    "llamacpp": {
        "label": "Ether-Spark",
        "description": "Primary local chat/runtime lane",
        "base_url": "http://127.0.0.1:18081/v1",
        "model": "qwen-3.5-35b-a3b",
    },
    "llamacpp-long": {
        "label": "Ether-Spark Long",
        "description": "Long-context runtime",
        "base_url": "http://ether-spark:18084/v1",
        "model": "qwen-3.5-35b-a3b-long",
    },
    "llamacpp-distilled": {
        "label": "Ether5",
        "description": "Experimental distilled coding runtime",
        "base_url": "http://192.168.146.164:1234/v1",
        "model": "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2",
    },
    "llamacpp-alt": {
        "label": "Ether-9",
        "description": "Experimental alternate runtime",
        "base_url": "http://192.168.146.22:8080/v1",
        "model": "Qwen3.5-27B-Q4_K_M",
    },
}

LOCAL_PROVIDER_ORDER = (
    "llamacpp",
    "llamacpp-long",
    "llamacpp-distilled",
    "llamacpp-alt",
)


@dataclass(frozen=True)
class ChatRuntime:
    provider: str
    label: str
    base_url: str
    chat_url: str
    model: str


@dataclass(frozen=True)
class ProviderStatusTarget:
    provider: str
    name: str
    description: str
    host: str
    port: int
    models_url: str


def get_openclaw_config_path() -> str:
    """Resolve the active OpenClaw config path for this overlay."""
    env_path = (
        os.environ.get("OPENCLAW_CONFIG_PATH")
        or os.environ.get("MISSION_CONTROL_OPENCLAW_CONFIG_PATH")
        or ""
    ).strip()
    if env_path:
        return os.path.expanduser(env_path)
    if CANONICAL_OPENCLAW_CONFIG_PATH.exists():
        return str(CANONICAL_OPENCLAW_CONFIG_PATH)
    return str(DEFAULT_OPENCLAW_CONFIG_PATH)


def load_openclaw_config() -> Dict[str, Any]:
    """Load the active OpenClaw config, returning an empty dict if unavailable."""
    config_path = get_openclaw_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def build_openclaw_subprocess_env(base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Inject the active OpenClaw config path into child CLI processes."""
    env = dict(base_env or os.environ)
    path_entries = [OPENCLAW_BIN_DIR]
    current_path = env.get("PATH", "")
    if current_path:
        path_entries.append(current_path)
    env["PATH"] = ":".join(path_entries)
    env["OPENCLAW_CONFIG_PATH"] = get_openclaw_config_path()
    return env


def _normalize_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _first_model_id(provider_cfg: Dict[str, Any], fallback_model: str) -> str:
    models = provider_cfg.get("models", [])
    if not isinstance(models, list):
        return fallback_model
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            return model_id
    return fallback_model


def get_chat_runtime(provider_name: str = PRIMARY_LLM_PROVIDER) -> ChatRuntime:
    """Resolve a provider's base URL and primary model from OpenClaw config."""
    provider_key = str(provider_name or "").strip() or PRIMARY_LLM_PROVIDER
    defaults = PROVIDER_DEFAULTS.get(provider_key, PROVIDER_DEFAULTS["llamacpp"])
    providers = load_openclaw_config().get("models", {}).get("providers", {})
    provider_cfg = providers.get(provider_key) if isinstance(providers, dict) else {}
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}

    base_url = _normalize_base_url(provider_cfg.get("baseUrl") or defaults["base_url"])
    model = _first_model_id(provider_cfg, defaults["model"])

    return ChatRuntime(
        provider=provider_key,
        label=str(defaults["label"]),
        base_url=base_url,
        chat_url=f"{base_url}/chat/completions",
        model=model,
    )


def get_primary_chat_runtime() -> ChatRuntime:
    """Resolve the default Mission Control internal LLM lane."""
    return get_chat_runtime(PRIMARY_LLM_PROVIDER)


def get_local_provider_status_targets() -> Iterable[ProviderStatusTarget]:
    """Expose local OpenAI-compatible model runtimes for health checks."""
    providers = load_openclaw_config().get("models", {}).get("providers", {})
    if not isinstance(providers, dict):
        providers = {}

    for provider_name in LOCAL_PROVIDER_ORDER:
        defaults = PROVIDER_DEFAULTS[provider_name]
        provider_cfg = providers.get(provider_name) if isinstance(providers.get(provider_name), dict) else {}
        base_url = _normalize_base_url((provider_cfg or {}).get("baseUrl") or defaults["base_url"])
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
        if not host:
            continue

        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80

        yield ProviderStatusTarget(
            provider=provider_name,
            name=str(defaults["label"]),
            description=str(defaults["description"]),
            host=host,
            port=port,
            models_url=f"{base_url}/models",
        )


async def run_primary_chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
    runtime: Optional[ChatRuntime] = None,
) -> Optional[str]:
    """Call the primary OpenAI-compatible local runtime and return message content."""
    target = runtime or get_primary_chat_runtime()
    payload = {
        "model": target.model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    timeout_config = httpx.Timeout(connect=5.0, read=float(timeout), write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout_config) as client:
        response = await client.post(
            target.chat_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    if response.status_code != 200:
        return None

    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
