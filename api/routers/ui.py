"""Server-rendered HTML routes for the Mission Control v2 UI.

The application root (``/``) is a lightweight **hub** that links to
Project-Box for tasks. Project-Box replaced the v1 Kanban board.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from api.middleware.auth import get_current_user
from config import ROOT_DIR, get_settings
from services import surface_registry

templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

router = APIRouter(tags=["ui"])


def _surface_context(request: Request, *, page: str) -> dict[str, Any]:
    settings = get_settings()
    current_surface = surface_registry.get_surface(page, settings)
    return {
        "page": page,
        "username": get_current_user(request),
        "app_surfaces": surface_registry.nav_surfaces(settings),
        "current_surface": current_surface,
        "wide_surface": bool(
            current_surface
            and (
                current_surface["kind"] == "embedded"
                or current_surface.get("wide")
            )
        ),
    }


def _voice_secure_synapse_url() -> str:
    settings = get_settings()
    voice_url = settings.ether_voice_public_url.strip()
    if not voice_url:
        return ""
    parsed = urlparse(voice_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return f"https://{parsed.hostname}/synapse"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def control_hub(request: Request) -> HTMLResponse:
    """Mission Control hub — tasks open in Project-Box."""
    settings = get_settings()
    ctx = _surface_context(request, page="hub")
    ctx["hub_surfaces"] = surface_registry.hub_surfaces(settings)
    return templates.TemplateResponse(
        request=request,
        name="hub.html",
        context=ctx,
    )


@router.get("/kanban", include_in_schema=False)
async def kanban_redirect() -> RedirectResponse:
    """v1 ``/`` was Kanban; that role now belongs to Project-Box."""
    settings = get_settings()
    target = settings.projectbox_public_url or settings.projectbox_url
    return RedirectResponse(url=target, status_code=302)


@router.get("/briefing", response_class=HTMLResponse, include_in_schema=False)
async def briefing_page(request: Request) -> HTMLResponse:
    """Daily briefing dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="briefing.html",
        context=_surface_context(request, page="briefing"),
    )


@router.get("/constellation", response_class=HTMLResponse, include_in_schema=False)
async def constellation_page(request: Request) -> HTMLResponse:
    """OpenClaw constellation dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="constellation.html",
        context=_surface_context(request, page="constellation"),
    )


@router.get("/synapse", response_class=HTMLResponse, include_in_schema=False)
async def synapse_page(request: Request) -> HTMLResponse:
    """Synapse multi-agent terminal."""
    ctx = _surface_context(request, page="synapse")
    ctx["voice_secure_synapse_url"] = _voice_secure_synapse_url()
    return templates.TemplateResponse(
        request=request,
        name="synapse.html",
        context=ctx,
    )


@router.get("/nexus", include_in_schema=False)
async def nexus_redirect() -> RedirectResponse:
    """v1 Nexus route now points to Synapse."""
    return RedirectResponse(url="/synapse", status_code=302)


@router.get("/email", response_class=HTMLResponse, include_in_schema=False)
async def email_page(request: Request) -> HTMLResponse:
    """Email triage placeholder with API hints."""
    ctx = _surface_context(request, page="email")
    ctx.update(
        {
            "page_title": "Email triage",
            "page_lead": (
                "Pipeline stages and decisions live in Postgres. "
                "Use the JSON API until the full triage UI ships."
            ),
            "api_hint": (
                "Try <a href='/api/emails'>GET /api/emails</a> and "
                "<code>POST /api/emails/{id}/decision</code>."
            ),
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="placeholder.html",
        context=ctx,
    )


@router.get("/queue", response_class=HTMLResponse, include_in_schema=False)
async def queue_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="queue.html",
        context=_surface_context(request, page="queue"),
    )


@router.get("/crm", include_in_schema=False)
async def crm_redirect() -> RedirectResponse:
    """CRM lives in Twenty; keep /crm as a compatibility redirect."""
    settings = get_settings()
    target = settings.twenty_crm_public_url or settings.twenty_crm_url
    return RedirectResponse(url=target, status_code=302)


@router.get("/tasks", response_class=HTMLResponse, include_in_schema=False)
async def tasks_redirect(request: Request) -> RedirectResponse:
    """Tasks live in Project-Box — redirect browser clients."""
    settings = get_settings()
    target = settings.projectbox_public_url or settings.projectbox_url
    return RedirectResponse(url=target, status_code=302)
