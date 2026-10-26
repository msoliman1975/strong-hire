"""Strong Hire API. P0 exposes /health; P2 adds the job target and resume input routes; P6 adds
the gap analysis routes; P8 adds the debrief and progress routes; P9 adds billing (/billing) and
account self-service (/account). R1 adds the saved job and CV library and /reports. R2 adds
the admin area (/admin). A6 adds the public /status (site banner, paused controls). C2 adds the
Custom interview routes (/custom, /questions/mine). L04 adds /public (the waitlist)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.account import install_account
from strong_api.admin import install_admin, seed_admins_on_startup
from strong_api.auth import install_auth
from strong_api.billing import install_billing
from strong_api.controls import router as status_router
from strong_api.custom.router import router as custom_router
from strong_api.devtools import router as dev_router
from strong_api.gap.router import router as gap_router
from strong_api.inputs import router as inputs_router
from strong_api.inputs.queue import ArqJobQueue, JobQueue
from strong_api.observability import RequestContextMiddleware
from strong_api.public import install_public
from strong_api.questions import router as questions_router
from strong_api.reports import router as reports_router
from strong_api.scoring import router as scoring_router
from strong_api.sessions.feedback import router as feedback_router
from strong_api.sessions.router import router as sessions_router
from strong_core import __version__
from strong_core.config import get_settings
from strong_core.db import get_engine, get_sessionmaker
from strong_core.ops import logs as ops_logs
from strong_core.ops.heartbeat import read_heartbeats
from strong_core.ops.runtime import start_ops

Check = Callable[[], Awaitable[None]]
WorkerCheck = Callable[[], Awaitable[int]]


def configure_logging() -> None:
    """Show INFO logs of the app's own packages (uvicorn sets up only its own loggers), as text
    or as JSON lines (LOG_FORMAT, OB-7).

    Adds a handler to the root logger only when it has none, so a host that set up logging
    (or pytest) keeps its own. Other libraries stay at WARNING.
    """
    ops_logs.configure_logging("api", app_loggers=("strong_api", "strong_interview"))


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def worker_heartbeats() -> int:
    """AL-8: the number of live worker heartbeats (OB-1) in Redis."""
    client = Redis.from_url(get_settings().redis_url)
    try:
        return len(await read_heartbeats(client, "worker"))
    finally:
        await client.aclose()


async def check_redis() -> None:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


def create_app(
    checks: dict[str, Check] | None = None,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    queue: JobQueue | None = None,
    worker_check: WorkerCheck | None = None,
) -> FastAPI:
    """`worker_check` counts live worker heartbeats for /health (AL-8). It defaults to Redis
    when `checks` is not given either; with test checks and no worker check, it is skipped."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await seed_admins_on_startup(app)  # AA-1
        # OB-1 heartbeat, OB-2 usage sink, OB-4 error capture. Not run by the test clients.
        ops = await start_ops("api", maker=app.state.sessionmaker)
        try:
            yield
        finally:
            await app.state.queue.close()
            await ops.stop()

    app = FastAPI(title="Strong Hire API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5180", "http://localhost:5181"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)  # OB-7 request ids, OB-4 unhandled errors
    app.state.checks = checks or {"database": check_database, "redis": check_redis}
    app.state.worker_check = worker_check or (worker_heartbeats if checks is None else None)
    app.state.sessionmaker = sessionmaker or get_sessionmaker()
    app.state.queue = queue or ArqJobQueue(settings.redis_url)
    app.include_router(inputs_router)
    app.include_router(gap_router)
    app.include_router(scoring_router)
    app.include_router(sessions_router)
    app.include_router(feedback_router)
    app.include_router(reports_router)
    app.include_router(questions_router)
    app.include_router(custom_router)
    app.include_router(dev_router)
    app.include_router(status_router)
    install_auth(app)
    install_billing(app)
    install_account(app)
    install_admin(app)
    install_public(app)  # L04: waitlist

    @app.get("/health")
    async def health(response: Response) -> dict[str, Any]:
        results: dict[str, str] = {}
        for name, check in app.state.checks.items():
            try:
                await asyncio.wait_for(check(), timeout=3)
                results[name] = "ok"
            except Exception as exc:
                results[name] = f"error: {type(exc).__name__}"
        healthy = all(v == "ok" for v in results.values())
        # AL-8: the external uptime check on /health also covers the worker (and with it the
        # alert engine): no live worker heartbeat means 503.
        worker, workers = "skipped", None
        if app.state.worker_check is not None:
            try:
                workers = await asyncio.wait_for(app.state.worker_check(), timeout=3)
                worker = "ok" if workers else "missing"
            except Exception as exc:
                worker = f"error: {type(exc).__name__}"
            healthy = healthy and worker == "ok"
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "model_profile": settings.model_profile.value,
            "checks": results,
            "worker": worker,
            "worker_instances": workers,
        }

    return app


configure_logging()
app = create_app()
