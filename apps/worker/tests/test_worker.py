from __future__ import annotations

from strong_worker.main import WorkerSettings, ping


async def test_ping() -> None:
    assert await ping({}) == "pong"
    assert ping in WorkerSettings.functions
