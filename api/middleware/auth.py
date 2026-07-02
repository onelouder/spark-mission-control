"""Authentication middleware and FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from services import auth_service

PUBLIC_EXACT_PATHS = frozenset({"/login", "/logout", "/api/health"})
PUBLIC_PREFIXES = ("/static/",)


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


class AuthMiddleware(BaseHTTPMiddleware):
    """Require a valid ``session_token`` cookie on all non-public routes."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not auth_service.auth_is_enabled():
            return await call_next(request)

        if _is_public_path(request.url.path):
            return await call_next(request)

        username = await auth_service.verify_session_token(
            request.cookies.get("session_token")
        )
        if username:
            request.state.username = username
            return await call_next(request)

        if _wants_html(request):
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )


def get_current_user(request: Request) -> Optional[str]:
    """Return the authenticated username attached by :class:`AuthMiddleware`."""
    return getattr(request.state, "username", None)
