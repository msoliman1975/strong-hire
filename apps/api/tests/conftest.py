from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_api.inputs.queue import JobInfo
from strong_api.main import create_app
from strong_core.config import get_settings
from strong_core.db.models import Base, Company
from strong_core.db.seed import LAUNCH_COMPANIES
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_worker.inputs import jobs
from strong_worker.inputs.jobs import CTX_KEY, InputsContext
from strong_worker.inputs.storage import LocalEncryptedFileStore
from strong_worker.inputs.testing import (
    RecordingBackend,
    copy_fake_fixtures,
    enable_sqlite_jsonb,
    make_fetcher,
)

enable_sqlite_jsonb()


@pytest.fixture(autouse=True)
def _fake_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROFILE", "fake")
    monkeypatch.setenv("ENV", "test")
    get_settings.cache_clear()


class InlineQueue:
    """Runs the real worker job functions in the test, instead of through Redis and Arq."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        self.ctx = ctx
        self.run_jobs = True
        self.enqueued: list[tuple[str, str, dict[str, Any]]] = []
        self.results: dict[str, dict[str, Any]] = {}

    async def enqueue(self, function: str, job_id: str, **kwargs: Any) -> None:
        self.enqueued.append((function, job_id, kwargs))
        if self.run_jobs:
            self.results[job_id] = await getattr(jobs, function)(self.ctx, **kwargs)

    async def info(self, job_id: str) -> JobInfo:
        if job_id in self.results:
            return JobInfo(job_id, "complete", result=self.results[job_id])
        if any(j == job_id for _, j, _ in self.enqueued):
            return JobInfo(job_id, "queued")
        return JobInfo(job_id, "not_found")

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_fixtures(tmp_path: Path) -> Path:
    return copy_fake_fixtures(tmp_path / "fake-fixtures")


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add_all(Company(slug=slug, name=name) for slug, name in LAUNCH_COMPANIES)
        await db.commit()
    yield maker
    await engine.dispose()


@pytest.fixture
def ctx(
    sessionmaker: async_sessionmaker[AsyncSession], fake_fixtures: Path, tmp_path: Path
) -> dict[str, Any]:
    gateway = ModelGateway(fake_models_config(), fake=RecordingBackend(fake_fixtures))
    return {
        CTX_KEY: InputsContext(
            sessionmaker=sessionmaker,
            gateway=gateway,
            store=LocalEncryptedFileStore(tmp_path / "files", Fernet.generate_key()),
            fetcher=make_fetcher({}),
        )
    }


@pytest.fixture
def queue(ctx: dict[str, Any]) -> InlineQueue:
    return InlineQueue(ctx)


async def _ok() -> None:
    return None


@pytest.fixture
def app(sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue) -> FastAPI:
    return create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
