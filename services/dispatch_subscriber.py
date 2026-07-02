"""Background subscriber that mirrors Synapse run-status into PostgreSQL.

The FastAPI ``lifespan`` starts a single :func:`run` task; it pulls events
from :func:`services.openclaw_client.subscribe_run_updates`, opens a
fresh DB session per event, and lets
:func:`services.dispatch_service.apply_run_status_event` translate the
event into ORM updates.

Design constraints:
    - Idempotent against reload: ``lifespan`` cancels the task on
      shutdown and we swallow ``CancelledError`` cleanly.
    - Resilient: any non-cancellation exception is logged and the loop
      reconnects after a short back-off so a flaky gateway doesn't take
      the whole API down.
    - Offline-safe: when no gateway URL is configured the loop exits
      immediately without ever attempting a connection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from db.session import get_session_factory
from services import dispatch_service, openclaw_client

logger = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 5.0


async def run() -> None:
    """Long-running subscriber loop. Cancel to stop.

    Should be wrapped in an :class:`asyncio.Task` by the FastAPI lifespan
    so cancellation propagates cleanly on shutdown.
    """
    if not openclaw_client.gateway_url():
        logger.info("dispatch_subscriber: no MOLTBOT_GATEWAY_WS_URL set; idle")
        return

    factory = get_session_factory()
    while True:
        try:
            async for event in openclaw_client.subscribe_run_updates():
                async with factory() as session:
                    try:
                        await dispatch_service.apply_run_status_event(session, event)
                        await session.commit()
                    except Exception:
                        logger.exception(
                            "dispatch_subscriber: failed to apply event"
                        )
                        await session.rollback()
        except asyncio.CancelledError:
            logger.info("dispatch_subscriber: cancelled, exiting")
            raise
        except Exception:
            logger.exception(
                "dispatch_subscriber: stream errored; reconnecting in %.1fs",
                RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def start_in_lifespan() -> Optional[asyncio.Task]:
    """Spawn the subscriber as a background task.

    Returns ``None`` when no gateway URL is configured so the lifespan
    doesn't have to special-case the offline path.
    """
    if not openclaw_client.gateway_url():
        return None
    return asyncio.create_task(run(), name="mc2-dispatch-subscriber")


async def stop_in_lifespan(task: Optional[asyncio.Task]) -> None:
    """Cancel ``task`` and wait for it to finish, swallowing CancelledError."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("dispatch_subscriber: error during shutdown")
