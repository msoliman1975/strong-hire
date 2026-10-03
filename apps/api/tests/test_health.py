from __future__ import annotations

from fastapi.testclient import TestClient

from strong_api.main import create_app


async def _ok() -> None:
    return None


async def _down() -> None:
    raise ConnectionError("down")


def test_health_ok() -> None:
    client = TestClient(create_app({"database": _ok, "redis": _ok}))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_health_degraded_when_a_dependency_is_down() -> None:
    client = TestClient(create_app({"database": _ok, "redis": _down}))
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "error: ConnectionError"
