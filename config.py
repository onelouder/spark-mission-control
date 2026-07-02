"""Application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Environment-backed settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://user:password@localhost:5433/database"
    redis_url: str = "redis://localhost:6380/0"
    host: str = "0.0.0.0"
    port: int = 3000
    public_base_url: str = "http://127.0.0.1:3000"
    decapoda_base_url: str = "http://localhost:8766"
    v1_data_dir: Path = ROOT_DIR.parent / "mission-control" / "data"
    secrets_data_dir: Path = ROOT_DIR / "data"

    # Project-Box / Flow Focus integration. The Mission Control v2 task surface
    # (Kanban + per-task focus timer) is being retired in favor of Project-Box,
    # which writes Markdown task files into an Obsidian vault. v2 talks to it
    # via its REST API; set ``projectbox_url`` to an empty string to opt out
    # (e.g. during automated tests or when running offline).
    projectbox_url: str = "http://127.0.0.1:5173"
    projectbox_public_url: str = "http://127.0.0.1:5173"
    projectbox_timeout_seconds: float = 5.0
    projectbox_cache_ttl_seconds: int = 30

    # Twenty CRM integration. Mission Control embeds the browser UI; Twenty
    # remains the owner of CRM data and API behavior.
    twenty_crm_url: str = "http://127.0.0.1:3200"
    twenty_crm_public_url: str = "http://127.0.0.1:3200"

    # OpenClaw agent config directory. Leave unset until the operator confirms
    # the live per-agent config ownership path.
    openclaw_config_dir: Path | None = None
    moltbot_gateway_ws_url: str = ""
    moltbot_token: str = ""
    moltbot_gateway_insecure_tls: bool = True

    # Ether-Voice speech appliance. Mission Control attaches as an agent client
    # on the northbound Agent Session Protocol; the browser still uses the
    # appliance's own WebRTC client for mic/speaker media.
    ether_voice_agent_ws_url: str = ""
    ether_voice_agent_auth: str = ""
    ether_voice_public_url: str = ""
    ether_voice_default_voice: str = "bm_daniel"
    ether_voice_agent_voices: str = ""
    ether_voice_default_model: str = ""
    ether_voice_agent_models: str = ""
    ether_voice_wake_phrases: str = ""
    ether_voice_agent_wake_phrases: str = ""

    # Session auth (v1-compatible env names). Set ``auth_enabled=false`` for
    # local dev/tests; production should always set ``mission_control_password_hash``.
    auth_enabled: bool = True
    mission_control_username: str = "admin"
    mission_control_password_hash: str = ""
    session_secret: str = "change-me-in-production"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 8

    # Runway attendee filter — exclude self from meeting headcount when set.
    auth_self_email: str = ""


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
