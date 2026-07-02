"""Send one message to an agent's persistent main session and print the reply."""
import asyncio
import os
import sys
import uuid

os.environ.setdefault("MOLTBOT_GATEWAY_INSECURE_TLS", "1")

from services import openclaw_client  # noqa: E402
from services.openclaw_client import GatewayConnection  # noqa: E402

TERMINAL = {"completed", "failed", "aborted", "error", "final", "done"}


async def main(agent_id: str, prompt: str) -> None:
    key = openclaw_client.AGENT_REGISTRY[agent_id]["session_key"]
    conn = GatewayConnection()
    await conn.connect(timeout=10)
    res = await conn.request(
        "chat.send",
        {"sessionKey": key, "message": prompt, "idempotencyKey": "sd-" + uuid.uuid4().hex[:10]},
        timeout=20,
    )
    print(f"sent to {key}; runId={(res.get('payload') or {}).get('runId') or res.get('runId')}")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 120
    last = ""
    try:
        while loop.time() < deadline:
            try:
                frame = await asyncio.wait_for(conn.next_event(), timeout=deadline - loop.time())
            except asyncio.TimeoutError:
                break
            p = frame.get("payload") or {}
            status = str(p.get("status") or p.get("phase") or "").lower()
            msg = p.get("message")
            if isinstance(msg, dict):
                msg = msg.get("content") or msg.get("text") or ""
                if isinstance(msg, list):
                    msg = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in msg)
            if msg:
                last = msg
            if status in TERMINAL or str(p.get("type") or "").lower() in TERMINAL or p.get("final"):
                break
    finally:
        await conn.close()
    print(f"REPLY[{len(last)}]: {(last or '').strip().replace(chr(10), ' ')[:400]!r}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
