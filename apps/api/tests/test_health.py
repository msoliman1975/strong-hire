from __future__ import annotations

from fastapi.testclient import TestClient

from strong_api.main import create_app


async def _ok() -> None:
    return None


async def _down() -> None:
    raise ConnectionError("down")


async def _one_worker() -> int:
    return 1


async def _no_worker() -> int:
    return 0


async def _redis_gone() -> int:
    raise ConnectionError("down")


def test_health_ok() -> None:
    client = TestClient(create_app({"database": _ok, "redis": _ok}, worker_check=_one_worker))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}
    assert body["worker"] == "ok" and body["worker_instances"] == 1


def test_health_degraded_when_a_dependency_is_down() -> None:
    client = TestClient(create_app({"database": _ok, "redis": _down}, worker_check=_one_worker))
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "error: ConnectionError"


def test_al8_health_fails_when_no_worker_heartbeat() -> None:
    """AL-8: the external uptime check on /health also covers the worker (OB-1 heartbeat)."""
    client = TestClient(create_app({"database": _ok, "redis": _ok}, worker_check=_no_worker))
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded" and body["worker"] == "missing"
    assert body["checks"] == {"database": "ok", "redis": "ok"}  # the old shape is kept

    broken = TestClient(create_app({"database": _ok}, worker_check=_redis_gone))
    resp = broken.get("/health")
    assert resp.status_code == 503 and resp.json()["worker"] == "error: ConnectionError"


def test_al8_worker_check_is_skipped_for_test_checks_without_one() -> None:
    client = TestClient(create_app({"database": _ok}))
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["worker"] == "skipped"
