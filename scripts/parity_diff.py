"""Sprint 4 — parity diff between v1 (port 3000) and v2 (port 3001).

The goal isn't byte-for-byte parity; v1 still owns the LLM-driven briefing
blocks (``threads``, ``pulse``) and the Decapoda-backed ``runway`` block,
plus an authentication layer v2 now mirrors with Redis-backed sessions. This tool surfaces the
*shape* of each major endpoint side-by-side so the operator can sign off
on cut-over.

What it does:
    1. Hits a curated list of GET endpoints on both v1 and v2.
    2. For each pair, prints status code + top-level keys.
    3. Flags endpoints that only exist on one side (v1-only = "still to
       port"; v2-only = "new in v2").
    4. Writes a structured JSON report to ``--out`` when supplied.

What it deliberately does **not** do:
    - Compare payload values. Many fields (timestamps, generated ids)
      will always drift; full diffing is left to dedicated golden tests.
    - Mutate either service. All requests are GET; v2 may require a session
      cookie when ``AUTH_ENABLED=true``.

Usage::

    python scripts/parity_diff.py
    python scripts/parity_diff.py --v1 http://127.0.0.1:3000 \\
        --v2 http://127.0.0.1:3001 --out parity-report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("parity_diff")


PAIRS: list[tuple[str, str]] = [
    # v1 path                  v2 path
    # v1's /api/tasks is now obsolete — Project-Box owns the canonical
    # task system. v2 still serves /api/tasks during cut-over but the
    # source of truth is /api/projectbox/tasks (proxied to port 5173).
    ("/api/tasks",             "/api/projectbox/tasks"),
    ("/api/queue",             "/api/queue"),
    ("/api/briefing",          "/api/briefing/today"),
    ("/api/briefing/runway",   "/api/briefing/runway"),
    ("/api/briefing/threads",  None),
    ("/api/briefing/pulse",    None),
    ("/api/snooze",            "/api/briefing/snoozes"),
    ("/api/contacts",          "/api/contacts"),
    ("/api/contexts",          "/api/contexts"),
    ("/api/accounts",          "/api/accounts"),
    (None,                     "/api/projectbox/health"),
]


@dataclass
class EndpointReport:
    """Pair-wise report row for a single (v1, v2) endpoint comparison."""

    v1_path: Optional[str]
    v2_path: Optional[str]
    v1_status: Optional[int] = None
    v2_status: Optional[int] = None
    v1_keys: list[str] = field(default_factory=list)
    v2_keys: list[str] = field(default_factory=list)
    note: str = ""


async def _probe(
    client: httpx.AsyncClient, base: str, path: str
) -> tuple[Optional[int], list[str], str]:
    """Fetch ``base + path`` and return ``(status, top-level-keys, note)``."""
    try:
        response = await client.get(base + path, timeout=10.0)
    except httpx.HTTPError as exc:
        return None, [], f"transport error: {exc}"
    note = ""
    keys: list[str] = []
    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            note = "non-JSON body"
        else:
            if isinstance(body, dict):
                keys = sorted(body.keys())
            elif isinstance(body, list):
                keys = ["<list>"]
                note = f"list len={len(body)}"
            else:
                note = f"scalar={type(body).__name__}"
    return response.status_code, keys, note


async def run(v1_base: str, v2_base: str, out_path: Optional[str]) -> int:
    """Run the side-by-side probe; print a summary; return exit code."""
    reports: list[EndpointReport] = []
    async with httpx.AsyncClient() as client:
        for v1_path, v2_path in PAIRS:
            report = EndpointReport(v1_path=v1_path, v2_path=v2_path)
            if v1_path:
                report.v1_status, report.v1_keys, note = await _probe(
                    client, v1_base, v1_path
                )
                if note and not report.note:
                    report.note = f"v1: {note}"
            if v2_path:
                report.v2_status, report.v2_keys, note = await _probe(
                    client, v2_base, v2_path
                )
                if note:
                    sep = "; " if report.note else ""
                    report.note = f"{report.note}{sep}v2: {note}"
            if v1_path and not v2_path:
                report.note = (report.note + "; " if report.note else "") + (
                    "still to port (lives in v1 only)"
                )
            if v2_path and not v1_path:
                report.note = (report.note + "; " if report.note else "") + (
                    "new in v2"
                )
            reports.append(report)

    _print_table(reports)
    if out_path:
        with open(out_path, "w") as fh:
            json.dump([asdict(r) for r in reports], fh, indent=2, sort_keys=True)
        logger.info("parity report written → %s", out_path)
    return 0


def _print_table(reports: list[EndpointReport]) -> None:
    """Print a compact ASCII summary of the parity probe."""
    print(f"\n{'v1 path':30s}  {'v2 path':30s}  {'v1':>4s}  {'v2':>4s}  notes")
    print("-" * 110)
    for r in reports:
        v1 = r.v1_path or "—"
        v2 = r.v2_path or "—"
        v1_status = str(r.v1_status) if r.v1_status is not None else "—"
        v2_status = str(r.v2_status) if r.v2_status is not None else "—"
        print(f"{v1:30s}  {v2:30s}  {v1_status:>4s}  {v2_status:>4s}  {r.note}")


def main() -> int:
    """CLI entrypoint — keeps the module importable for tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v1",
        default="http://127.0.0.1:3000",
        help="v1 base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--v2",
        default="http://127.0.0.1:3001",
        help="v2 base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write a JSON parity report",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    import asyncio

    return asyncio.run(run(args.v1, args.v2, args.out))


if __name__ == "__main__":
    sys.exit(main())
