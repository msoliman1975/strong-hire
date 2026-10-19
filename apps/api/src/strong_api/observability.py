"""Request ids, log context and unhandled-error capture for the API (admin spec OB-4, OB-7).

RequestContextMiddleware (pure ASGI, so streaming responses are untouched):
- takes X-Request-ID from the request when it is a short safe token, else makes one, and
  returns it in the X-Request-ID response header;
- tags every log line of the request with request_id, and with session_id when the path names
  a session (/sessions/<uuid>/...);
- logs an unhandled exception at ERROR with its traceback (the error capture handler stores
  it, scrubbed, with the request id) and re-raises, so the 500 response is unchanged. Request
  bodies are never read here.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from strong_core.ops.logs import log_context

log = logging.getLogger("strong_api.errors")

REQUEST_ID_HEADER = "x-request-id"
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SESSION_PATH = re.compile(r"/sessions/([0-9a-fA-F-]{36})(?:/|$)")


def request_id_from(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name.decode("latin-1").lower() == REQUEST_ID_HEADER:
            candidate = str(value.decode("latin-1")).strip()
            if SAFE_REQUEST_ID.match(candidate):
                return candidate
    return uuid.uuid4().hex[:16]


def session_id_from_path(path: str) -> str | None:
    match = SESSION_PATH.search(path)
    if match is None:
        return None
    try:
        return str(uuid.UUID(match.group(1)))
    except ValueError:
        return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from(scope)
        path = str(scope.get("path") or "")
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        with log_context(request_id=request_id, session_id=session_id_from_path(path)):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                log.exception("unhandled error on %s %s", scope.get("method"), _route(scope))
                raise


def _route(scope: Scope) -> str:
    """The route template (/sessions/{session_id}) when known, so ids stay out of messages."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return template
    return SESSION_PATH.sub("/sessions/{id}/", str(scope.get("path") or ""))
