"""Strong Hire API. P0 exposes /health; P2 adds the job target and resume input routes; P6 adds
the gap analysis routes; P8 adds the debrief and progress routes; P9 adds billing (/billing) and
account self-service (/account). R1 adds the saved job and CV library and /reports. R2 adds
the admin area (/admin)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.account import install_account
from strong_api.admin import install_admin
from strong_api.auth import install_auth
from strong_api.billing import install_billing
from strong_api.devtools import router as dev_router
from strong_api.gap.router import router as gap_router
from strong_api.inputs import router as inputs_router
from strong_api.inputs.queue import ArqJobQueue, JobQueue
from strong_api.reports import router as reports_router
from strong_api.scoring import router as scoring_router
from strong_api.sessions.router import router as sessions_router
from strong_core import __version__
from strong_core.config import get_settings
from strong_core.db import get_engine, get_sessionmaker

Check = Callable[[], Awaitable[None]]
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Show INFO logs of the app's own packages (uvicorn sets up only its own loggers).

    Adds a handler to the root logger only when it has none, so a host that set up logging
    (or pytest) keeps its own. Other libraries stay at WARNING.
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    for name in ("strong_api", "strong_interview"):
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


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
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.queue.close()

    app = FastAPI(title="Strong Hire API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5180"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.checks = checks or {"database": check_database, "redis": check_redis}
    app.state.sessionmaker = sessionmaker or get_sessionmaker()
    app.state.queue = queue or ArqJobQueue(settings.redis_url)
    app.include_router(inputs_router)
    app.include_router(gap_router)
    app.include_router(scoring_router)
    app.include_router(sessions_router)
    app.include_router(reports_router)
    app.include_router(dev_router)
    install_auth(app)
    install_billing(app)
    install_account(app)
    install_admin(app)

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
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "model_profile": settings.model_profile.value,
            "checks": results,
        }

    return app


configure_logging()
app = create_app()
