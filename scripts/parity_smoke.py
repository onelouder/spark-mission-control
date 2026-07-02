#!/usr/bin/env python3
"""Smoke-test v2 API after migration."""

import json
import sys
import urllib.request

BASE = "http://localhost:3001"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    health = get("/api/health")
    print("health:", health)
    if health.get("checks", {}).get("postgres") != "ok":
        print("FAIL: postgres not ok")
        sys.exit(1)

    tasks = get("/api/tasks")
    count = len(tasks.get("tasks", []))
    print(f"tasks: {count}")
    if count == 0:
        print("WARN: no tasks (run migrate_json_to_pg.py?)")

    focus = get("/api/focus/status")
    print("focus:", focus)
    print("OK")


if __name__ == "__main__":
    main()
