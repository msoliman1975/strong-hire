"""IV-1: the dev test page gets a LiveKit token and the worker reports health."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import jwt
import pytest

from strong_voice.devserver import make_token, start_devserver
from strong_voice.settings import VoiceSettings


@pytest.fixture
def settings(tmp_path: Path) -> VoiceSettings:
    page = tmp_path / "devpage"
    page.mkdir()
    (page / "index.html").write_text("<title>spike</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    return VoiceSettings(voice_health_port=0, devpage_dir=page, livekit_public_url="ws://pub")


def _get(port: int, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_token_grants_one_room(settings: VoiceSettings) -> None:
    token = make_token(settings, "spike-1", "me")
    claims = jwt.decode(token, settings.livekit_api_secret, algorithms=["HS256"])
    assert claims["sub"] == "me"
    assert claims["video"]["room"] == "spike-1"
    assert claims["video"]["roomJoin"] is True


def test_devserver_serves_health_page_and_token(settings: VoiceSettings) -> None:
    server = start_devserver(settings, "fake")
    port = server.server_address[1]
    try:
        code, body = _get(port, "/health")
        assert code == 200
        assert json.loads(body)["profile"] == "fake"
        code, body = _get(port, "/")
        assert code == 200
        assert b"spike" in body
        code, body = _get(port, "/token?room=r1")
        data = json.loads(body)
        assert code == 200
        assert data["url"] == "ws://pub"
        assert data["room"] == "r1"
        assert _get(port, "/..%2Fsecret.txt")[0] == 404
    finally:
        server.shutdown()


def test_devserver_hides_token_outside_dev(settings: VoiceSettings) -> None:
    prod = settings.model_copy(update={"env": "prod"})
    server = start_devserver(prod, "hosted")
    port = server.server_address[1]
    try:
        assert _get(port, "/health")[0] == 200
        assert _get(port, "/token")[0] == 404
    finally:
        server.shutdown()
