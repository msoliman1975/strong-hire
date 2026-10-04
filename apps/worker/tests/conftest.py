from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.config import get_settings
from strong_core.db.models import Base, Company, Org, User
from strong_core.db.seed import LAUNCH_COMPANIES
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import AuthProvider
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
    """Tests never call a real model, except the opt-in accuracy run (STRONG_EVAL_INPUTS=1)."""
    if os.environ.get("STRONG_EVAL_INPUTS") != "1":
        monkeypatch.setenv("MODEL_PROFILE", "fake")
    get_settings.cache_clear()


@pytest.fixture
def fake_fixtures(tmp_path: Path) -> Path:
    """A copy of the default fake model fixtures that a test may change."""
    return copy_fake_fixtures(tmp_path / "fake-fixtures")


@pytest.fixture
def backend(fake_fixtures: Path) -> RecordingBackend:
    return RecordingBackend(fake_fixtures)


@pytest.fixture
def gateway(backend: RecordingBackend) -> ModelGateway:
    return ModelGateway(fake_models_config(), fake=backend)


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def account(sessionmaker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    """(org_id, user_id) of a test user, with the 20 launch companies seeded."""
    async with sessionmaker() as db:
        org = Org(name="Test org")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email="user@example.com", auth_provider=AuthProvider.DEV)
        db.add(user)
        db.add_all(Company(slug=slug, name=name) for slug, name in LAUNCH_COMPANIES)
        await db.commit()
        return org.id, user.id


@pytest.fixture
def store(tmp_path: Path) -> LocalEncryptedFileStore:
    return LocalEncryptedFileStore(tmp_path / "files", Fernet.generate_key())


@pytest.fixture
def ctx(
    sessionmaker: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    store: LocalEncryptedFileStore,
) -> dict[str, Any]:
    return {
        CTX_KEY: InputsContext(
            sessionmaker=sessionmaker, gateway=gateway, store=store, fetcher=make_fetcher({})
        )
    }
