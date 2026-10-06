"""Where a finished data export (AC-1) waits for its one download.

The worker writes the zip bundle to Redis with a time limit (ACCOUNT_EXPORT_TTL_S, default 24
hours). The download endpoint reads and deletes it in one step (GETDEL), so each export can be
downloaded once. Keys must match strong_worker.account.jobs.export_key (a test checks this).
"""

from __future__ import annotations

import time
import uuid
from typing import Protocol

from redis.asyncio import Redis

DOWNLOADED_TTL_S = 7 * 24 * 3600


def export_key(org_id: uuid.UUID | str, export_id: uuid.UUID | str) -> str:
    return f"account:export:{org_id}:{export_id}"


def export_job_id(org_id: uuid.UUID | str, export_id: uuid.UUID | str) -> str:
    return f"export:{org_id}:{export_id}"


class ExportStore(Protocol):
    async def exists(self, key: str) -> bool: ...

    async def take(self, key: str) -> bytes | None:
        """Return the bundle and delete it, or None when it is gone."""

    async def mark_downloaded(self, key: str) -> None: ...

    async def was_downloaded(self, key: str) -> bool: ...

    async def delete_org(self, org_id: uuid.UUID) -> int:
        """Delete every export of an org (account delete). Return how many keys went."""


class RedisExportStore:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    def _client(self) -> Redis:
        client: Redis = Redis.from_url(self._redis_url)
        return client

    async def exists(self, key: str) -> bool:
        client = self._client()
        try:
            return bool(await client.exists(key))
        finally:
            await client.aclose()

    async def take(self, key: str) -> bytes | None:
        client = self._client()
        try:
            data = await client.getdel(key)
        finally:
            await client.aclose()
        return bytes(data) if data is not None else None

    async def mark_downloaded(self, key: str) -> None:
        client = self._client()
        try:
            await client.set(f"{key}:downloaded", "1", ex=DOWNLOADED_TTL_S)
        finally:
            await client.aclose()

    async def was_downloaded(self, key: str) -> bool:
        client = self._client()
        try:
            return bool(await client.exists(f"{key}:downloaded"))
        finally:
            await client.aclose()

    async def delete_org(self, org_id: uuid.UUID) -> int:
        client = self._client()
        removed = 0
        try:
            async for key in client.scan_iter(match=f"{export_key(org_id, '*')}"):
                removed += int(await client.delete(key))
        finally:
            await client.aclose()
        return removed


class MemoryExportStore:
    """For tests. The worker side writes with `put`."""

    def __init__(self) -> None:
        self.data: dict[str, tuple[bytes, float]] = {}

    async def put(self, key: str, data: bytes, ttl_s: int) -> None:
        self.data[key] = (data, time.monotonic() + ttl_s)

    def _live(self, key: str) -> bytes | None:
        item = self.data.get(key)
        if item is None or item[1] < time.monotonic():
            self.data.pop(key, None)
            return None
        return item[0]

    async def exists(self, key: str) -> bool:
        return self._live(key) is not None

    async def take(self, key: str) -> bytes | None:
        data = self._live(key)
        self.data.pop(key, None)
        return data

    async def mark_downloaded(self, key: str) -> None:
        self.data[f"{key}:downloaded"] = (b"1", time.monotonic() + DOWNLOADED_TTL_S)

    async def was_downloaded(self, key: str) -> bool:
        return self._live(f"{key}:downloaded") is not None

    async def delete_org(self, org_id: uuid.UUID) -> int:
        prefix = export_key(org_id, "")
        keys = [k for k in self.data if k.startswith(prefix)]
        for k in keys:
            del self.data[k]
        return len(keys)
