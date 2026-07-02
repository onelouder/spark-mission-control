"""One-shot: abort wedged agent run(s) via the OpenClaw gateway.

Reuses the production GatewayConnection so the abort path is identical to
Synapse's own "reset session" button (chat.abort with the registry sessionKey).
Usage: python scripts/abort_stuck_session.py jarvis [atlas ...]
"""
import asyncio
import os
import sys

os.environ.setdefault("MOLTBOT_GATEWAY_INSECURE_TLS", "1")

from services import openclaw_client  # noqa: E402
from services.openclaw_client import GatewayConnection  # noqa: E402


async def main(agent_ids: list[str]) -> None:
    conn = GatewayConnection()
    await conn.connect(timeout=10)
    print("connected to gateway")
    try:
        for agent_id in agent_ids:
            try:
                key = openclaw_client.AGENT_REGISTRY[agent_id]["session_key"]
            except KeyError:
                print(f"  {agent_id}: NOT in AGENT_REGISTRY, skipping")
                continue
            try:
                res = await conn.request(
                    "chat.abort", {"sessionKey": key}, timeout=15
                )
                print(f"  {agent_id} ({key}): abort ok -> {res.get('result', res.get('ok'))}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {agent_id} ({key}): abort FAILED -> {exc!r}")
    finally:
        await conn.close()
        print("closed")


if __name__ == "__main__":
    targets = sys.argv[1:] or ["jarvis"]
    asyncio.run(main(targets))
