from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strong_core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Async engine. DATABASE_URL uses the psycopg 3 driver, which works sync and async."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
