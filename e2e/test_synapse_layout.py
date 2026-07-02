"""Opt-in Playwright checks for the Synapse browser layout."""

from __future__ import annotations

import os

import pytest


BASE_URL = os.environ.get("MC2_E2E_BASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL,
        reason="Set MC2_E2E_BASE_URL to run Playwright browser checks.",
    ),
]


def test_synapse_header_is_compact(page) -> None:
    from playwright.sync_api import expect

    assert BASE_URL is not None
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL.rstrip('/')}/synapse")

    title_group = page.locator(".synapse-title-group")
    toolbar = page.locator(".synapse-toolbar")
    shell = page.locator(".synapse-shell")

    expect(title_group).to_be_visible()
    expect(toolbar).to_be_visible()
    expect(shell).to_be_visible()

    title_box = title_group.bounding_box()
    toolbar_box = toolbar.bounding_box()
    shell_box = shell.bounding_box()

    assert title_box is not None
    assert toolbar_box is not None
    assert shell_box is not None
    assert title_box["height"] <= 24
    assert toolbar_box["height"] <= 34
    assert shell_box["height"] >= 820
