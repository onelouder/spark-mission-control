/**
 * Mission Control v2 — health badge.
 *
 * Polls /api/health every 30 seconds and recolors the dot in the navbar
 * so degraded Postgres/Redis is immediately visible.
 *
 * Classes (defined in mission-control.css overrides at the bottom of the page):
 *   .health-badge--ok        green
 *   .health-badge--degraded  amber
 *   .health-badge--down      red
 *   .health-badge--unknown   grey  (initial state, also on fetch failure)
 */
(function () {
    "use strict";

    const POLL_MS = 30_000;
    const badge = document.getElementById("health-badge");
    if (!badge) {
        return;
    }

    function setState(state, detail) {
        badge.classList.remove(
            "health-badge--ok",
            "health-badge--degraded",
            "health-badge--down",
            "health-badge--unknown",
        );
        badge.classList.add(`health-badge--${state}`);
        if (detail) {
            badge.title = detail;
        }
    }

    async function poll() {
        try {
            const response = await fetch("/api/health", { cache: "no-store" });
            if (!response.ok) {
                setState("down", `HTTP ${response.status}`);
                return;
            }
            const payload = await response.json();
            const checks = payload.checks || {};
            const detail =
                `Postgres: ${checks.postgres || "?"} | ` +
                `Redis: ${checks.redis || "?"} | ` +
                `Project-Box: ${checks.projectbox || "?"} | ` +
                `OpenClaw: ${checks.openclaw || "?"} | ` +
                `App: ${checks.mission_control_v2 || "?"}`;
            if (payload.status === "ok") {
                setState("ok", detail);
            } else {
                setState("degraded", detail);
            }
        } catch (err) {
            setState("down", err.message || "fetch failed");
        }
    }

    poll();
    setInterval(poll, POLL_MS);
})();
