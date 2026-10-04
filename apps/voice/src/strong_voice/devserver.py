"""Small HTTP server next to the worker: health, plus the dev test page and its tokens.

    GET /health                       always
    GET /                             apps/voice/devpage/index.html (dev only)
    GET /token?room=..&identity=..    LiveKit join token for the dev page (dev only)

The dev page is a bare test page for the spike, not the product web app.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from livekit import api

from strong_voice.settings import VoiceSettings


def make_token(settings: VoiceSettings, room: str, identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
    )
    return token.to_jwt()


def _handler(settings: VoiceSettings, profile: str) -> type[BaseHTTPRequestHandler]:
    devpage = settings.devpage_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: dict[str, object]) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/health":
                self._json(200, {"status": "ok", "service": "voice", "profile": profile})
                return
            if settings.env != "dev":
                self._json(404, {"error": "not found"})
                return
            if url.path == "/token":
                q = parse_qs(url.query)
                room = q.get("room", ["spike"])[0][:64] or "spike"
                identity = q.get("identity", [""])[0][:64] or f"candidate-{uuid.uuid4().hex[:6]}"
                self._json(
                    200,
                    {
                        "url": settings.livekit_public_url or settings.livekit_url,
                        "token": make_token(settings, room, identity),
                        "room": room,
                        "identity": identity,
                    },
                )
                return
            name = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
            path = (devpage / name).resolve()
            if devpage not in path.parents or not path.is_file():
                self._json(404, {"error": "not found"})
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), ctype)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def start_devserver(settings: VoiceSettings, profile: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        ("0.0.0.0", settings.voice_health_port), _handler(settings, profile)
    )
    threading.Thread(target=server.serve_forever, name="voice-devserver", daemon=True).start()
    return server
