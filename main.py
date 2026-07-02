"""Mission Control v2 — FastAPI application entrypoint."""

import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from api.routers import (
    accomplishments,
    accounts,
    auth,
    briefing,
    constellation,
    email,
    projectbox,
    queue,
    synapse,
    system,
    tasks,
    ui,
)
from api.middleware.auth import AuthMiddleware
from cache.redis_client import close_redis, get_redis
from config import ROOT_DIR, get_settings
from db.session import dispose_engine, get_engine
from logging_config import configure_logging
from services import auth_service, dispatch_subscriber, snooze_service, synapse_hub

configure_logging()
logger = logging.getLogger("mission_control_v2.main")
access_logger = logging.getLogger("mission_control_v2.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify DB and Redis, launch subscriber. Shutdown: release."""
    logger.info("Mission Control v2 starting")
    auth_service.configure_auth()
    get_engine()
    await get_redis()
    subscriber_task = dispatch_subscriber.start_in_lifespan()
    snooze_task = snooze_service.start_in_lifespan()
    await synapse_hub.HUB.start()  # no-op when no gateway URL is configured
    try:
        yield
    finally:
        logger.info("Mission Control v2 shutting down")
        await synapse_hub.HUB.stop()
        await snooze_service.stop_in_lifespan(snooze_task)
        await dispatch_subscriber.stop_in_lifespan(subscriber_task)
        await close_redis()
        await dispose_engine()


app = FastAPI(
    title="Mission Control v2",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next) -> Response:
    """Emit a single access-log line per HTTP request.

    Format mirrors what uvicorn's own access log produces but routes
    through the centralized ``mission_control_v2.access`` logger so
    structured-logging changes apply everywhere.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000.0
    client = request.client.host if request.client else "-"
    access_logger.info(
        '%s %s "%s %s" %d %.1fms',
        client,
        request.scope.get("http_version", "1.1"),
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(system.router)
app.include_router(auth.router)
app.include_router(constellation.router)
app.include_router(tasks.router)
app.include_router(queue.router)
app.include_router(synapse.router)
app.include_router(email.router)
app.include_router(briefing.router)
app.include_router(accounts.router)
app.include_router(accomplishments.router)
app.include_router(projectbox.router)
app.include_router(ui.router)

static_dir = ROOT_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def run() -> None:
    """Run uvicorn."""
    settings = get_settings()
    logger.info("Mission Control v2 listening on %s", settings.public_base_url)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
