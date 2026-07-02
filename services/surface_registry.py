"""Registry for Mission Control UI surfaces.

The app bar and hub cards both render from this list so wrapped apps stay
visible everywhere without duplicating links across templates.
"""

from __future__ import annotations

from typing import Any

from config import Settings, get_settings


Surface = dict[str, Any]


def all_surfaces(settings: Settings | None = None) -> list[Surface]:
    """Return the canonical Mission Control UI surfaces."""
    settings = settings or get_settings()
    projectbox_url = settings.projectbox_public_url or settings.projectbox_url
    crm_url = settings.twenty_crm_public_url or settings.twenty_crm_url

    return [
        {
            "id": "hub",
            "label": "Hub",
            "title": "Control plane",
            "description": "Mission Control overview.",
            "kind": "internal",
            "href": "/",
            "show_in_nav": True,
            "show_on_hub": False,
        },
        {
            "id": "constellation",
            "label": "Constellation",
            "title": "OpenClaw constellation",
            "description": "Synapse gateway, agents, runs, and configs.",
            "kind": "internal",
            "href": "/constellation",
            "show_in_nav": True,
            "show_on_hub": True,
            "primary": True,
        },
        {
            "id": "synapse",
            "label": "Synapse",
            "title": "Multi-agent terminal",
            "description": "Chat, terminal streams, and live agent control.",
            "kind": "internal",
            "href": "/synapse",
            "wide": True,
            "show_in_nav": True,
            "show_on_hub": True,
            "primary": True,
        },
        {
            "id": "briefing",
            "label": "Briefing",
            "title": "Daily briefing",
            "description": "Runway + decisions + stale.",
            "kind": "internal",
            "href": "/briefing",
            "show_in_nav": True,
            "show_on_hub": True,
        },
        {
            "id": "email",
            "label": "Email",
            "title": "Triage",
            "description": "API: /api/emails.",
            "kind": "internal",
            "href": "/email",
            "show_in_nav": True,
            "show_on_hub": True,
        },
        {
            "id": "crm",
            "label": "CRM",
            "title": "Twenty CRM",
            "description": "Open Twenty CRM.",
            "kind": "external",
            "href": crm_url,
            "external_url": crm_url,
            "show_in_nav": True,
            "show_on_hub": True,
        },
        {
            "id": "queue",
            "label": "Queue",
            "title": "Agent queue",
            "description": "Live agent summary.",
            "kind": "internal",
            "href": "/queue",
            "wide": True,
            "show_in_nav": True,
            "show_on_hub": True,
        },
        {
            "id": "tasks",
            "label": "Tasks",
            "title": "Open Project-Box",
            "description": "Flow Focus task workspace.",
            "kind": "external",
            "href": projectbox_url,
            "external_url": projectbox_url,
            "show_in_nav": True,
            "show_on_hub": True,
        },
    ]


def nav_surfaces(settings: Settings | None = None) -> list[Surface]:
    """Return surfaces shown in the top app bar."""
    return [s for s in all_surfaces(settings) if s["show_in_nav"]]


def hub_surfaces(settings: Settings | None = None) -> list[Surface]:
    """Return surfaces shown as hub cards."""
    return [s for s in all_surfaces(settings) if s["show_on_hub"]]


def get_surface(surface_id: str, settings: Settings | None = None) -> Surface | None:
    """Find a single surface by id."""
    for surface in all_surfaces(settings):
        if surface["id"] == surface_id:
            return surface
    return None
