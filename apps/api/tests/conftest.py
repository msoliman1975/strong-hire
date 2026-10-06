"""Test helpers. API tests run on in-memory SQLite, so they need no Docker and no Postgres."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_api.auth import get_db, install_auth
from strong_api.auth.magic_links import MagicLinks, MemoryUsedTokenStore
from strong_api.auth.settings import AppEnv, AuthSettings
from strong_api.inputs.queue import JobInfo
from strong_api.main import create_app
from strong_core.config import get_settings
from strong_core.db.models import Base, Company
from strong_core.db.seed import LAUNCH_COMPANIES
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap.jobs import GapContext
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


WORKER_FUNCTIONS = {f.__name__: f for f in (*jobs.FUNCTIONS, *gap_jobs.FUNCTIONS)}


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
            self.results[job_id] = await WORKER_FUNCTIONS[function](self.ctx, **kwargs)

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
        ),
        gap_jobs.CTX_KEY: GapContext(sessionmaker=sessionmaker, gateway=gateway),
    }


@pytest.fixture
def queue(ctx: dict[str, Any]) -> InlineQueue:
    return InlineQueue(ctx)


async def _ok() -> None:
    return None


@pytest.fixture
def app(sessionmaker: async_sessionmaker[AsyncSession], queue: InlineQueue) -> FastAPI:
    return create_app({"database": _ok}, sessionmaker=sessionmaker, queue=queue)


async def sign_in(http: httpx.AsyncClient, email: str = "dev@example.com") -> dict[str, Any]:
    """Sign in with the local dev login (P3), and sign up on the first visit."""
    state: dict[str, Any] = (await http.post("/auth/dev-login", json={"email": email})).json()
    if state["status"] == "needs_signup":
        body = {"age_confirmed": True, "terms_accepted": True}
        state = (await http.post("/auth/signup", json=body)).json()
    assert state["status"] == "signed_in", state
    return state


@pytest.fixture
async def anon_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client with nobody signed in."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in as dev@example.com."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await sign_in(http)
        yield http


# Sign-in (P3)


class RecordingEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_magic_link(self, to: str, link: str) -> None:
        self.sent.append((to, link))


class AuthHarness:
    def __init__(self, app: FastAPI, client: TestClient, sessionmaker: Any, email: Any) -> None:
        self.app = app
        self.client = client
        self.sessionmaker: async_sessionmaker[AsyncSession] = sessionmaker
        self.email: RecordingEmailSender = email

    def query(self, fn: Any) -> Any:
        """Run `await fn(db_session)` on the test database and return the result."""

        async def _run() -> Any:
            async with self.sessionmaker() as db:
                return await fn(db)

        return self.client.portal.call(_run)  # type: ignore[union-attr]


def build_harness(app_env: AppEnv = AppEnv.LOCAL, google: Any = None) -> Iterator[AuthHarness]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    settings = AuthSettings(
        app_env=app_env,
        session_secret="x" * 40,
        web_base_url="http://web.test",
        api_public_url="http://web.test/api",
    )
    email = RecordingEmailSender()
    app = FastAPI()
    install_auth(
        app,
        settings,
        magic_links=MagicLinks(settings.session_secret, 900, MemoryUsedTokenStore()),
        email_sender=email,
        google=google,
    )
    app.dependency_overrides[get_db] = _db
    with TestClient(app, base_url="http://web.test") as client:
        client.portal.call(_create_all, engine)  # type: ignore[union-attr]
        yield AuthHarness(app, client, sessionmaker, email)
        client.portal.call(engine.dispose)  # type: ignore[union-attr]


async def _create_all(engine: Any) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def auth() -> Iterator[AuthHarness]:
    yield from build_harness()
