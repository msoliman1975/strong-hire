from __future__ import annotations

from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strong_core.config import get_settings


def async_database_url(url: str) -> str:
    """DATABASE_URL uses psycopg (sync: Alembic, scripts). Async code uses asyncpg, which also
    works on the default Windows event loop, unlike psycopg's async mode."""
    return make_url(url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(async_database_url(get_settings().database_url), pool_pre_ping=True)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
