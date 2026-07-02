"""Try to fully reset an agent's persistent session (fresh codex thread)."""
import asyncio, os, sys
os.environ.setdefault("MOLTBOT_GATEWAY_INSECURE_TLS", "1")
from services import openclaw_client  # noqa: E402
from services.openclaw_client import GatewayConnection  # noqa: E402

async def main(agent_id):
    key = openclaw_client.AGENT_REGISTRY[agent_id]["session_key"]
    conn = GatewayConnection(); await conn.connect(timeout=10)
    try:
        res = await conn.request("sessions.reset", {"key": key}, timeout=20)
        print(f"sessions.reset {key}: OK -> {res.get('ok', res.get('result', res))}")
    except Exception as e:
        print(f"sessions.reset {key}: {e!r}")
    await conn.close()

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "atlas"))
