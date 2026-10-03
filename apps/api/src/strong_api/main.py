"""Strong Hire API. P0 only exposes /health; product routes arrive in later workstreams."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from strong_core import __version__
from strong_core.config import get_settings
from strong_core.db import get_engine

Check = Callable[[], Awaitable[None]]


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


def create_app(checks: dict[str, Check] | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Strong Hire API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5180"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.checks = checks or {"database": check_database, "redis": check_redis}

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


app = create_app()
