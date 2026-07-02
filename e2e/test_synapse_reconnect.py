"""Opt-in Playwright check: Synapse auto-reconnects without a page reload.

Reproduces the original "chat stagnation" failure mode: the WebSocket drops
(server restart stands in for a proxy idle-close or gateway blip) and the
page must recover live updates on its own — no manual reload.

Run:
    MC2_E2E_RECONNECT=1 venv/bin/python -m pytest e2e/test_synapse_reconnect.py \
        -q --browser chromium

Manages its own uvicorn on port 8788 so it never disturbs a dev server.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

import pytest

PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("MC2_E2E_RECONNECT"),
        reason="Set MC2_E2E_RECONNECT=1 to run the reconnect browser check.",
    ),
]


def _start_server() -> subprocess.Popen:
    import httpx

    proc = subprocess.Popen(
        [
            os.path.join(ROOT, "venv", "bin", "python"),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
    )
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                return proc
        except Exception:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("verification server did not become healthy")


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_synapse_auto_reconnects_without_reload(page) -> None:
    from playwright.sync_api import expect

    page_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    proc = _start_server()
    try:
        page.goto(f"{BASE}/synapse")
        status = page.locator("#synapse-status")
        expect(status).to_have_text("Connected", timeout=15000)
        # A reload would wipe this marker — it must survive recovery.
        page.evaluate("window.__no_reload_marker = true")

        _stop_server(proc)
        expect(status).to_have_text(
            re.compile("Disconnected|Error|Connecting"), timeout=15000
        )

        proc = _start_server()
        # Backoff schedule: ~0.5/1/2/4/8/16s (+jitter) — allow the tail.
        expect(status).to_have_text("Connected", timeout=45000)

        assert page.evaluate("window.__no_reload_marker") is True, (
            "page reloaded during recovery — reconnect must be in-place"
        )
        assert page_errors == [], f"unexpected page errors: {page_errors}"
    finally:
        _stop_server(proc)
