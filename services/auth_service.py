"""Session authentication for Mission Control v2.

Ports the v1 emergency auth (SHA-256 + salt, ``session_token`` cookie)
but stores sessions in Redis so they survive process restarts and work
across multiple workers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from cache.redis_client import get_redis
from config import get_settings

logger = logging.getLogger(__name__)

PASSWORD_SALT = "mission_control_salt_2025"
SESSION_KEY_PREFIX = "mc:session:"

_effective_password_hash: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash a password using the v1-compatible SHA-256 + salt scheme."""
    return hashlib.sha256((password + PASSWORD_SALT).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Return ``True`` when ``password`` matches ``hashed``."""
    return hash_password(password) == hashed


def configure_auth() -> None:
    """Resolve the effective password hash once at startup."""
    global _effective_password_hash
    settings = get_settings()
    if not settings.auth_enabled:
        _effective_password_hash = None
        logger.info("auth: disabled (AUTH_ENABLED=false)")
        return

    if settings.mission_control_password_hash:
        _effective_password_hash = settings.mission_control_password_hash
        logger.info(
            "auth: enabled for user %r (hash from env)",
            settings.mission_control_username,
        )
        return

    default_password = "MissionControl2025!"
    _effective_password_hash = hash_password(default_password)
    logger.warning(
        "auth: MISSION_CONTROL_PASSWORD_HASH unset — using emergency default "
        "password for user %r (change immediately)",
        settings.mission_control_username,
    )


def auth_is_enabled() -> bool:
    """Return whether auth middleware should enforce sessions."""
    return get_settings().auth_enabled


def get_password_hash() -> str:
    """Return the configured password hash (must call ``configure_auth`` first)."""
    if _effective_password_hash is None:
        configure_auth()
    assert _effective_password_hash is not None
    return _effective_password_hash


def _session_ttl() -> timedelta:
    return timedelta(hours=get_settings().session_ttl_hours)


def session_max_age_seconds() -> int:
    """Cookie ``max_age`` / Redis TTL in seconds."""
    return int(_session_ttl().total_seconds())


async def create_session(username: str) -> str:
    """Create a Redis-backed session and return its opaque token."""
    token = secrets.token_urlsafe(32)
    payload = {
        "username": username,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    redis = await get_redis()
    await redis.set(
        f"{SESSION_KEY_PREFIX}{token}",
        json.dumps(payload),
        ex=session_max_age_seconds(),
    )
    return token


async def verify_session_token(token: Optional[str]) -> Optional[str]:
    """Return the username for ``token``, or ``None`` if invalid/expired."""
    if not token:
        return None
    redis = await get_redis()
    raw = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await redis.delete(f"{SESSION_KEY_PREFIX}{token}")
        return None
    username = payload.get("username")
    if not username:
        return None
    # Sliding expiry on each verified request.
    await redis.expire(
        f"{SESSION_KEY_PREFIX}{token}",
        int(_session_ttl().total_seconds()),
    )
    return str(username)


async def delete_session(token: Optional[str]) -> None:
    """Remove a session token from Redis."""
    if not token:
        return
    redis = await get_redis()
    await redis.delete(f"{SESSION_KEY_PREFIX}{token}")
