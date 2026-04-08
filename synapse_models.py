#!/usr/bin/env python3
"""Shared Synapse model catalog helpers."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
import ipaddress
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from openclaw_runtime import get_openclaw_config_path

DISPLAY_NAMES = {
    "anthropic/claude-opus-4-5": "Claude Opus 4.5",
    "anthropic/claude-opus-4-6": "Claude Opus 4.6",
    "anthropic/claude-sonnet-4-20250514": "Claude Sonnet 4",
    "anthropic/claude-sonnet-4-6": "Claude Sonnet 4.6",
    "google/gemini-2.5-pro": "Gemini 2.5 Pro",
    "google/gemini-2.5-flash": "Gemini 2.5 Flash",
    "google/gemini-3-pro": "Gemini 3 Pro",
    "google/gemini-3-pro-preview": "Gemini 3 Pro (Preview)",
    "google/gemini-3-flash": "Gemini 3 Flash",
    "google/gemini-3-flash-preview": "Gemini 3 Flash (Preview)",
    "openai/gpt-5.4": "GPT-5.4",
    "openai/gpt-5.4-pro": "GPT-5.4 Pro",
    "llamacpp/qwen-3.5-35b-a3b": "Ether-Spark — Qwen 35B",
    "llamacpp-long/qwen-3.5-35b-a3b-long": "Ether-Spark — Qwen 35B Long (262k)",
    "ether9-qwen/Qwen3.5-27B-Q4_K_M": "Qwen 3.5 27B Q4_K_M (Ether-9)",
    "llamacpp-alt/Qwen3.5-27B-Q4_K_M": "Ether-9 — Qwen 27B Q4_K_M",
    "llamacpp-distilled/qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2": "Ether5 — Qwen 27B Distilled Coding",
    "llama-local/gemma-4-26B-A4B-it-Q8_0.gguf": "Gemma 4 26B A4B (llama.cpp ⚡)",
}

FALLBACK_MODELS = (
    {"id": "anthropic/claude-sonnet-4-20250514", "label": "Claude Sonnet 4", "alias": "sonnet"},
    {"id": "anthropic/claude-opus-4-5", "label": "Claude Opus 4.5", "alias": "opus"},
)

_CACHE_LOCK = threading.Lock()
_CACHE_KEY: Optional[Tuple[str, int, int]] = None
_CACHE_VALUE: Optional["ModelCatalog"] = None
_CACHE_EXPIRES_AT = 0.0
_LIVE_MODEL_CACHE_TTL_SEC = 15.0
_LIVE_MODEL_CACHE: Dict[str, Tuple[float, frozenset[str], Optional[str]]] = {}


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    alias: str = ""
    short_id: str = ""


@dataclass(frozen=True)
class ModelCatalog:
    models: Tuple[ModelOption, ...]
    canonical_by_input: Dict[str, str]
    display_by_id: Dict[str, str]
    presets: Dict[str, str]
    blocked_models: Dict[str, str]
    config_path: str
    mtime_ns: int = 0
    size: int = 0
    error: Optional[str] = None

    @property
    def valid_inputs(self) -> frozenset[str]:
        return frozenset(self.canonical_by_input.keys())

    def resolve(self, model: str) -> str:
        value = str(model or "").strip()
        if not value:
            return ""
        return self.canonical_by_input.get(value) or self.canonical_by_input.get(value.lower()) or value

    def display_name(self, model: str) -> str:
        canonical = self.resolve(model)
        if canonical in self.display_by_id:
            return self.display_by_id[canonical]
        tail = canonical.split("/")[-1] if "/" in canonical else canonical
        return tail.replace("-", " ").title() if tail else canonical

    def to_api_payload(self) -> dict:
        return {
            "ok": True,
            "models": [
                {
                    "id": model.id,
                    "fullId": model.id,
                    "label": model.label,
                    "alias": model.alias,
                    "shortId": model.short_id,
                }
                for model in self.models
            ],
            "presets": dict(self.presets),
            "blockedModels": dict(self.blocked_models),
            "fallback": bool(self.error),
            "error": self.error,
        }


def _model_haystack(model: ModelOption) -> str:
    return f"{model.id} {model.alias} {model.label} {model.short_id}".lower()


def _pick_model(models: List[ModelOption], used: set[str], keyword_groups: List[List[str]]) -> str:
    for keywords in keyword_groups:
        matches = [
            model for model in models
            if model.id not in used and all(keyword in _model_haystack(model) for keyword in keywords)
        ]
        if matches:
            matches.sort(key=lambda model: (model.label.lower(), model.id.lower()))
            return matches[0].id
    return ""


def _infer_presets(models: List[ModelOption]) -> Dict[str, str]:
    if not models:
        return {"fast": "", "balanced": "", "deep": ""}

    used: set[str] = set()

    fast = _pick_model(models, used, [["flash"], ["haiku"], ["mini"], ["lite"]])
    if fast:
        used.add(fast)

    balanced = _pick_model(models, used, [["sonnet"], ["balanced"]])
    if balanced:
        used.add(balanced)

    deep = _pick_model(models, used, [["opus"], ["o3"], ["o1"], ["pro"]])
    if deep:
        used.add(deep)

    presets = {"fast": fast, "balanced": balanced, "deep": deep}
    remaining = [model.id for model in models if model.id not in used]
    for key in ("fast", "balanced", "deep"):
        if not presets[key]:
            presets[key] = remaining.pop(0) if remaining else (models[0].id if models else "")
    return presets


def _register_input(mapping: Dict[str, str], ambiguous: set[str], key: str, model_id: str):
    value = str(key or "").strip()
    if not value:
        return
    for candidate in {value, value.lower()}:
        existing = mapping.get(candidate)
        if existing is None and candidate not in ambiguous:
            mapping[candidate] = model_id
        elif existing and existing != model_id:
            mapping.pop(candidate, None)
            ambiguous.add(candidate)


def _build_catalog(
    raw_models: Dict[str, dict],
    config_path: str,
    mtime_ns: int,
    size: int,
    error: Optional[str] = None,
    blocked_models: Optional[Dict[str, str]] = None,
) -> ModelCatalog:
    entries: List[ModelOption] = []
    canonical_by_input: Dict[str, str] = {}
    ambiguous_inputs: set[str] = set()
    display_by_id: Dict[str, str] = {}

    for model_id, info in raw_models.items():
        if not isinstance(info, dict):
            info = {}
        alias = str(info.get("alias", "") or "").strip()
        short_id = model_id.split("/", 1)[1] if "/" in model_id else model_id
        label = DISPLAY_NAMES.get(model_id)
        if not label:
            label = alias.replace("-", " ").title() if alias else short_id.replace("-", " ").title()
        entries.append(ModelOption(id=model_id, label=label, alias=alias, short_id=short_id))
        display_by_id[model_id] = label
        _register_input(canonical_by_input, ambiguous_inputs, model_id, model_id)
        _register_input(canonical_by_input, ambiguous_inputs, short_id, model_id)
        _register_input(canonical_by_input, ambiguous_inputs, alias, model_id)

    entries.sort(key=lambda model: (model.label.lower(), model.id.lower()))
    deduped_entries: List[ModelOption] = []
    seen_ids = set()
    for entry in entries:
        if entry.id in seen_ids:
            continue
        seen_ids.add(entry.id)
        alias = entry.alias
        if alias and canonical_by_input.get(alias.lower()) != entry.id and canonical_by_input.get(alias) != entry.id:
            alias = ""
        deduped_entries.append(
            ModelOption(id=entry.id, label=entry.label, alias=alias, short_id=entry.short_id)
        )

    presets = _infer_presets(deduped_entries)
    return ModelCatalog(
        models=tuple(deduped_entries),
        canonical_by_input=canonical_by_input,
        display_by_id=display_by_id,
        presets=presets,
        blocked_models=dict(blocked_models or {}),
        config_path=config_path,
        mtime_ns=mtime_ns,
        size=size,
        error=error,
    )


def _build_fallback_catalog(config_path: str, error: str) -> ModelCatalog:
    raw_models = {
        entry["id"]: {"alias": entry.get("alias", "")}
        for entry in FALLBACK_MODELS
    }
    return _build_catalog(raw_models, config_path, 0, 0, error=error, blocked_models={})


def _fetch_live_model_ids(base_url: str) -> Tuple[frozenset[str], Optional[str]]:
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        return frozenset(), "Missing provider baseUrl"

    now = time.monotonic()
    cached = _LIVE_MODEL_CACHE.get(value)
    if cached and (now - cached[0]) < _LIVE_MODEL_CACHE_TTL_SEC:
        return cached[1], cached[2]

    endpoint = f"{value}/models"
    live_ids: set[str] = set()
    error: Optional[str] = None

    try:
        request = urllib.request.Request(
            endpoint,
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.load(response)

        for row in payload.get("data", []):
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            if model_id:
                live_ids.add(model_id)

        for row in payload.get("models", []):
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or row.get("model") or row.get("name") or "").strip()
            if model_id:
                live_ids.add(model_id)

        if not live_ids:
            error = f"No model ids returned by {endpoint}"
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive safety net
        error = str(exc)

    result = (frozenset(live_ids), error)
    _LIVE_MODEL_CACHE[value] = (now, result[0], result[1])
    return result


def _host_is_private_or_loopback(host: str) -> bool:
    value = str(host or "").strip().lower()
    if not value:
        return False
    if value in {"localhost", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def _should_validate_live_provider(provider_cfg: dict) -> bool:
    if not isinstance(provider_cfg, dict):
        return False

    base_url = str(provider_cfg.get("baseUrl") or "").strip()
    api = str(provider_cfg.get("api") or "").strip()
    api_key = str(provider_cfg.get("apiKey") or "").strip()
    provider_models = provider_cfg.get("models", [])
    host = urlparse(base_url).hostname or ""

    if api != "openai-completions" or not base_url or not isinstance(provider_models, list):
        return False

    return api_key == "local-not-used" or _host_is_private_or_loopback(host)


def _validate_runtime_models(
    config: dict,
    raw_models: Dict[str, dict],
    config_path: str,
) -> Tuple[Dict[str, dict], Dict[str, str], Optional[str]]:
    filtered_models = dict(raw_models)
    blocked_models: Dict[str, str] = {}
    warnings: List[str] = []

    providers = config.get("models", {}).get("providers", {})
    if not isinstance(providers, dict):
        return filtered_models, blocked_models, None

    for provider_name, provider_cfg in providers.items():
        if not _should_validate_live_provider(provider_cfg):
            continue

        base_url = str(provider_cfg.get("baseUrl") or "").strip()
        provider_models = provider_cfg.get("models", [])

        live_ids, live_error = _fetch_live_model_ids(base_url)
        if live_error:
            warnings.append(
                f"Could not verify live models for {provider_name} at {base_url}/models: {live_error}"
            )
            continue

        live_ids_text = ", ".join(sorted(live_ids)) if live_ids else "none"

        for row in provider_models:
            if not isinstance(row, dict):
                continue
            short_id = str(row.get("id") or "").strip()
            if not short_id or short_id in live_ids:
                continue

            canonical_id = f"{provider_name}/{short_id}"
            model_cfg = filtered_models.pop(canonical_id, None)
            reason = (
                f'Configured local model "{canonical_id}" is unavailable on the live OpenAI-compatible model server. '
                f'Live server reports: {live_ids_text}. Switch the agent to another model or realign '
                f"{config_path} with the running server at {base_url}."
            )
            blocked_models[canonical_id] = reason
            blocked_models[short_id] = reason

            if isinstance(model_cfg, dict):
                alias = str(model_cfg.get("alias") or "").strip()
                if alias:
                    blocked_models[alias] = reason

            warnings.append(
                f'Hid unavailable local model "{canonical_id}" because the live server reports: {live_ids_text}.'
            )

    warning_text = " ".join(warnings).strip() or None
    return filtered_models, blocked_models, warning_text


def get_model_catalog(force: bool = False) -> ModelCatalog:
    """Return a cached, normalized model catalog from openclaw.json."""
    global _CACHE_EXPIRES_AT, _CACHE_KEY, _CACHE_VALUE

    config_path = get_openclaw_config_path()
    try:
        stat_result = os.stat(config_path)
        cache_key = (config_path, stat_result.st_mtime_ns, stat_result.st_size)
    except OSError as exc:
        cache_key = (config_path, -1, -1)
        if (
            not force
            and _CACHE_KEY == cache_key
            and _CACHE_VALUE is not None
            and time.monotonic() < _CACHE_EXPIRES_AT
        ):
            return _CACHE_VALUE
        with _CACHE_LOCK:
            if (
                not force
                and _CACHE_KEY == cache_key
                and _CACHE_VALUE is not None
                and time.monotonic() < _CACHE_EXPIRES_AT
            ):
                return _CACHE_VALUE
            _CACHE_KEY = cache_key
            _CACHE_VALUE = _build_fallback_catalog(config_path, str(exc))
            _CACHE_EXPIRES_AT = time.monotonic() + _LIVE_MODEL_CACHE_TTL_SEC
            return _CACHE_VALUE

    if (
        not force
        and _CACHE_KEY == cache_key
        and _CACHE_VALUE is not None
        and time.monotonic() < _CACHE_EXPIRES_AT
    ):
        return _CACHE_VALUE

    with _CACHE_LOCK:
        if (
            not force
            and _CACHE_KEY == cache_key
            and _CACHE_VALUE is not None
            and time.monotonic() < _CACHE_EXPIRES_AT
        ):
            return _CACHE_VALUE
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            models_cfg = config.get("agents", {}).get("defaults", {}).get("models", {})
            if not isinstance(models_cfg, dict) or not models_cfg:
                raise ValueError("No models configured in openclaw.json")
            filtered_models, blocked_models, validation_error = _validate_runtime_models(
                config,
                models_cfg,
                config_path,
            )
            _CACHE_VALUE = _build_catalog(
                filtered_models,
                config_path,
                stat_result.st_mtime_ns,
                stat_result.st_size,
                error=validation_error,
                blocked_models=blocked_models,
            )
        except Exception as exc:
            _CACHE_VALUE = _build_fallback_catalog(config_path, str(exc))
        _CACHE_KEY = cache_key
        _CACHE_EXPIRES_AT = time.monotonic() + _LIVE_MODEL_CACHE_TTL_SEC
        return _CACHE_VALUE


def normalize_model_id(model: str) -> str:
    """Resolve aliases/short ids to canonical provider/model ids."""
    return get_model_catalog().resolve(model)


def explain_model_unavailability(model: str) -> Optional[str]:
    """Return a live-runtime mismatch reason when a configured model is unavailable."""
    value = str(model or "").strip()
    if not value:
        return None
    catalog = get_model_catalog()
    return catalog.blocked_models.get(value) or catalog.blocked_models.get(catalog.resolve(value))
