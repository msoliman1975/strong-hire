"""Log lines with service, request_id and session_id (admin spec OB-7).

    configure_logging("api")      # once, at process start
    with log_context(request_id="ab12", session_id=session.id):
        log.info("...")           # the line carries both ids

LOG_FORMAT=json writes one JSON object per line (the server sets it in compose.server.yaml),
so `docker logs api | grep <session id>` finds a session. LOG_FORMAT=text (the default) keeps
local logs readable and still shows the ids when they are set.

The session id comes from log_context, else from the gateway's usage context (worker jobs and
voice sessions set one), else from a LiveKit `room` attribute named session-<uuid> (records the
voice agent's job processes forward to the main process).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from strong_core.gateway.usage import current_usage_context

LOG_FORMAT_ENV = "LOG_FORMAT"
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s%(ctx)s: %(message)s"
SESSION_ROOM_PREFIX = "session-"
# Loggers that come with their own handlers. In JSON mode their handlers get the JSON formatter.
OWN_HANDLER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_request_id: ContextVar[str | None] = ContextVar("strong_log_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("strong_log_session_id", default=None)
_service = "app"


@contextmanager
def log_context(request_id: str | None = None, session_id: object | None = None) -> Iterator[None]:
    """Tag log lines in this block. None leaves the current value."""
    tokens = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if session_id is not None:
        tokens.append((_session_id, _session_id.set(str(session_id))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def current_service() -> str:
    return _service


def session_id_for(record: logging.LogRecord | None = None) -> str | None:
    """The session of a log record (or of the current context when no record is given)."""
    if record is not None:
        attached = getattr(record, "session_id", None)
        if attached:
            return str(attached)
    sid = _session_id.get()
    if sid:
        return sid
    usage = current_usage_context()
    if usage is not None and usage.session_id is not None:
        return str(usage.session_id)
    room = getattr(record, "room", None) if record is not None else None
    if isinstance(room, str) and room.startswith(SESSION_ROOM_PREFIX):
        return room.removeprefix(SESSION_ROOM_PREFIX)
    return None


class ContextFilter(logging.Filter):
    """Puts service, request_id and session_id on every record (never drops one)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "service", None):
            record.service = _service
        if not getattr(record, "request_id", None):
            record.request_id = _request_id.get()
        record.session_id = session_id_for(record)
        parts = [f"{k}={v}" for k in ("request_id", "session_id") if (v := getattr(record, k))]
        record.ctx = f" [{' '.join(parts)}]" if parts else ""
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, service, request_id, session_id."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", None) or _service,
            "request_id": getattr(record, "request_id", None),
            "session_id": getattr(record, "session_id", None) or session_id_for(record),
        }
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            line["exc"] = record.exc_text
        return json.dumps(line, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "ctx"):
            record.ctx = ""
        return super().format(record)


def log_format() -> str:
    value = os.environ.get(LOG_FORMAT_ENV, "text").strip().lower()
    return "json" if value == "json" else "text"


def make_formatter(fmt: str | None = None) -> logging.Formatter:
    return JsonFormatter() if (fmt or log_format()) == "json" else TextFormatter()


def configure_logging(
    service: str,
    *,
    app_loggers: tuple[str, ...] = (),
    fmt: str | None = None,
    drop_handlers: tuple[str, ...] = (),
) -> None:
    """Set the service name and one stream handler on the root logger (OB-7).

    A root logger that already has handlers (pytest, a host that set up logging) keeps them;
    they get the context filter only. `app_loggers` are set to INFO. `drop_handlers` names
    loggers whose own handlers are removed so their lines go through the root handler once
    (Arq's default handler, for example).
    """
    global _service
    _service = service
    formatter = make_formatter(fmt)
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_strong_ops", False)]
    if ours:
        for handler in ours:
            handler.setFormatter(formatter)
    elif not root.handlers:
        handler = logging.StreamHandler()
        handler._strong_ops = True  # type: ignore[attr-defined]
        handler.setFormatter(formatter)
        root.addHandler(handler)
    for handler in root.handlers:
        _add_filter(handler)
    for name in drop_handlers:
        logging.getLogger(name).handlers.clear()
    for name in OWN_HANDLER_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            _add_filter(handler)
            if isinstance(formatter, JsonFormatter):
                handler.setFormatter(formatter)
    for name in app_loggers:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


def _add_filter(handler: logging.Handler) -> None:
    if not any(isinstance(f, ContextFilter) for f in handler.filters):
        handler.addFilter(ContextFilter())
