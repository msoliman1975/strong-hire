"""Error capture into error_groups and error_events (admin spec OB-4).

ErrorCapture is a logging.Handler for ERROR and above. emit() only describes the record and
adds it to an in-memory batch under a lock, so it is cheap, thread-safe and never raises. A
background task (start()) writes the batch (write_pending()) every FLUSH_INTERVAL_S seconds:

- one error_groups row per fingerprint: count, first and last seen, service, release and one
  sample stack. A resolved group that happens again reopens (OB-12).
- at most one error_events row per group every EVENT_INTERVAL_S seconds (the count still goes
  up for every record), with the request id and session id when known.

Fingerprint: the exception type and the top 3 in-app frames (file:function, innermost first),
or the logger name and message template for an ERROR log without an exception. Records that
another process forwarded with the stack already formatted (the voice agent's job processes)
are parsed from that text.

PII (the L05 rules): request bodies, local variables and arguments are never read. Message
lines keep their first line only, cut to MAX_MESSAGE_WORDS words and MAX_MESSAGE_CHARS
characters, so resume or transcript text in an exception is never stored whole, and emails,
phone numbers and URL query strings are replaced. Stacks keep the frame lines and code lines,
with the same scrubbing on the exception message lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from strong_core.db.models import ErrorEvent, ErrorGroup
from strong_core.ops.heartbeat import release as current_release
from strong_core.ops.logs import current_request_id, session_id_for
from strong_core.schemas.enums import ErrorGroupStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)

EVENT_INTERVAL_S = 10.0
FLUSH_INTERVAL_S = 2.0
MAX_PENDING_GROUPS = 500
MAX_MESSAGE_WORDS = 12
MAX_MESSAGE_CHARS = 200
MAX_STACK_CHARS = 8000
TOP_FRAMES = 3
IN_APP_MARKER = "strong_"
# Never capture our own writes (a database outage would otherwise feed itself).
IGNORED_LOGGERS = ("strong_core.ops",)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_QUERY = re.compile(r"(https?://[^\s?#\"']+)\?[^\s#\"']*")
PHONE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w-])"
    r"|\+\d[\d\s-]{8,}\d"
)
FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line \d+, in (?P<func>.+)$')
EXC_LINE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::|$)")
STACK_MARKERS = ("Traceback (most recent call last)", "During handling", "The above exception")
VOLATILE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|0x[0-9a-f]+|\d+", re.I
)

_writing: ContextVar[bool] = ContextVar("strong_error_capture_writing", default=False)


# ------------------------------------------------------------------------------- scrubbing


def scrub_text(text: str) -> str:
    """Replace emails, URL query strings and phone numbers."""
    text = EMAIL.sub("[email]", text)
    text = URL_QUERY.sub(r"\1?[query]", text)
    return PHONE.sub("[phone]", text)


def scrub_message(text: str) -> str:
    """The first line only, scrubbed and cut, so free text is never kept whole."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    words = scrub_text(lines[0]).split()
    out = " ".join(words[:MAX_MESSAGE_WORDS])
    if len(words) > MAX_MESSAGE_WORDS or len(lines) > 1:
        out += " [text removed]"
    if len(out) > MAX_MESSAGE_CHARS:
        out = out[:MAX_MESSAGE_CHARS] + " [text removed]"
    return out


def scrub_stack(text: str) -> str:
    """Frame and code lines stay; each exception message keeps one scrubbed, cut line."""
    out: list[str] = []
    in_message = False
    for line in text.splitlines():
        if FRAME.match(line) or line.startswith(STACK_MARKERS):
            in_message = False
            out.append(scrub_text(line))
        elif in_message:
            continue  # the rest of a multi-line message: never kept
        elif line.startswith("    ") or not line.strip():
            out.append(scrub_text(line))
        else:
            out.append(scrub_message(line))
            in_message = True
    stack = "\n".join(out).strip()
    return stack[:MAX_STACK_CHARS]


# ----------------------------------------------------------------------------- fingerprints


def _short_path(path: str) -> str:
    path = path.replace("\\", "/")
    at = path.rfind("/" + IN_APP_MARKER)
    return path[at + 1 :] if at >= 0 else path.rsplit("/", 1)[-1]


def _frame_keys(frames: list[tuple[str, str]]) -> list[str]:
    """file:function of the top in-app frames, innermost first (any frames if none in-app)."""
    in_app = [f for f in frames if IN_APP_MARKER in f[0].replace("\\", "/")]
    chosen = (in_app or frames)[-TOP_FRAMES:]
    return [f"{_short_path(file)}:{func.strip()}" for file, func in reversed(chosen)]


def _type_name(exc_type: type[BaseException]) -> str:
    module = exc_type.__module__
    name = exc_type.__qualname__
    return name if module in ("builtins", "__main__") else f"{module}.{name}"


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", "replace")).hexdigest()


@dataclass(frozen=True)
class ErrorInfo:
    fingerprint: str
    exception_type: str
    message: str
    stack: str | None
    at: datetime
    request_id: str | None
    session_id: uuid.UUID | None


ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


def _from_exception(exc: ExcInfo) -> tuple[str, list[str], str, str]:
    exc_type, value, tb = exc
    type_name = _type_name(exc_type)
    frames = [(f.filename, f.name) for f in traceback.extract_tb(tb)]
    stack = "".join(traceback.format_exception(exc_type, value, tb))
    return type_name, _frame_keys(frames), scrub_message(str(value)), scrub_stack(stack)


def _from_text(exc_text: str) -> tuple[str, list[str], str, str]:
    """A stack that was formatted elsewhere: the last traceback block decides."""
    lines = exc_text.splitlines()
    start = max((i for i, line in enumerate(lines) if line.startswith(STACK_MARKERS[0])), default=0)
    block = lines[start:]
    frames = [(m["file"], m["func"]) for line in block if (m := FRAME.match(line))]
    type_name, message = "Error", ""
    for line in reversed(block):
        if (
            line
            and not line.startswith((" ", "\t", *STACK_MARKERS))
            and (m := EXC_LINE.match(line))
        ):
            type_name = m["type"]
            message = line[len(m["type"]) :].lstrip(": ")
            break
    return type_name, _frame_keys(frames), scrub_message(message), scrub_stack(exc_text)


def _session_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def describe(record: logging.LogRecord) -> ErrorInfo:
    """Fingerprint, type, scrubbed message and stack of one ERROR record."""
    exc = record.exc_info
    if exc and exc[0] is not None and exc[1] is not None:
        type_name, frames, message, stack = _from_exception(exc)
        fingerprint = _hash(type_name, *frames)
        stack_or_none: str | None = stack
    elif record.exc_text or "Traceback (most recent call last)" in str(record.msg):
        text = record.exc_text or str(record.msg)
        type_name, frames, message, stack = _from_text(text)
        fingerprint = _hash(type_name, *frames)
        stack_or_none = stack
    else:
        template = str(record.msg).strip().splitlines()[0] if str(record.msg).strip() else ""
        type_name = f"log:{record.name}"[:200]
        fingerprint = _hash(type_name, VOLATILE.sub("<n>", template))
        message = scrub_message(record.getMessage())
        stack_or_none = None
    request_id = getattr(record, "request_id", None) or current_request_id()
    return ErrorInfo(
        fingerprint=fingerprint,
        exception_type=type_name[:200],
        message=message,
        stack=stack_or_none,
        at=datetime.fromtimestamp(record.created, UTC),
        request_id=str(request_id)[:64] if request_id else None,
        session_id=_session_uuid(session_id_for(record)),
    )


# -------------------------------------------------------------------------------- the handler


@dataclass
class _Pending:
    info: ErrorInfo
    first_at: datetime
    count: int = 0
    events: list[ErrorInfo] = field(default_factory=list)


class ErrorCapture(logging.Handler):
    def __init__(
        self,
        service: str,
        maker: async_sessionmaker[AsyncSession],
        *,
        release: str | None = None,
        event_interval_s: float = EVENT_INTERVAL_S,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self.service = service
        self.maker = maker
        self.release_name = release or current_release()
        self.event_interval_s = event_interval_s
        self.flush_interval_s = flush_interval_s
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._last_event: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0

    # logging.Handler -------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _writing.get() or record.name.startswith(IGNORED_LOGGERS):
                return
            self.add(describe(record))
        except Exception:
            self.dropped += 1  # never raise from logging

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        return None  # never print "--- Logging error ---" for a capture failure

    def add(self, info: ErrorInfo) -> None:
        now = self._clock()
        with self._lock:
            pending = self._pending.get(info.fingerprint)
            if pending is None:
                if len(self._pending) >= MAX_PENDING_GROUPS:
                    self.dropped += 1
                    return
                pending = self._pending[info.fingerprint] = _Pending(info, info.at)
            pending.count += 1
            pending.info = info
            last = self._last_event.get(info.fingerprint)
            if last is None or now - last >= self.event_interval_s:
                self._last_event[info.fingerprint] = now
                pending.events.append(info)

    # the writer ------------------------------------------------------------------------

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"error-capture-{self.service}")
        return self._task

    async def stop(self, timeout_s: float = 5.0) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.write_pending(), timeout=timeout_s)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_s)
            await self.write_pending()

    async def write_pending(self) -> int:
        """Write what is pending. Returns the number of groups written. Never raises."""
        with self._lock:
            batch, self._pending = list(self._pending.values()), {}
        if not batch:
            return 0
        token = _writing.set(True)
        try:
            for attempt in (1, 2):
                try:
                    await self._write(batch)
                    return len(batch)
                except IntegrityError:
                    if attempt == 2:
                        raise  # another process kept inserting the same group
        except Exception as exc:
            log.warning("could not write %d error groups: %s", len(batch), type(exc).__name__)
        finally:
            _writing.reset(token)
        return 0

    async def _write(self, batch: list[_Pending]) -> None:
        async with self.maker() as db:
            for item in batch:
                info = item.info
                group_id = await db.scalar(
                    select(ErrorGroup.id).where(ErrorGroup.fingerprint == info.fingerprint)
                )
                if group_id is None:
                    group = ErrorGroup(
                        fingerprint=info.fingerprint,
                        service=self.service,
                        exception_type=info.exception_type,
                        message=info.message,
                        first_seen=item.first_at,
                        last_seen=info.at,
                        count=item.count,
                        status=ErrorGroupStatus.OPEN,
                        sample_stack=info.stack,
                        release=self.release_name,
                    )
                    db.add(group)
                    await db.flush()
                    group_id = group.id
                else:
                    await db.execute(
                        update(ErrorGroup)
                        .where(ErrorGroup.id == group_id)
                        .values(
                            count=ErrorGroup.count + item.count,
                            last_seen=info.at,
                            message=info.message,
                            service=self.service,
                            release=self.release_name,
                            status=ErrorGroupStatus.OPEN,  # OB-12: it happened again
                            resolved_at=None,
                            resolved_by=None,
                        )
                    )
                    if info.stack:
                        await db.execute(
                            update(ErrorGroup)
                            .where(ErrorGroup.id == group_id, ErrorGroup.sample_stack.is_(None))
                            .values(sample_stack=info.stack)
                        )
                for event in item.events:
                    db.add(
                        ErrorEvent(
                            group_id=group_id,
                            at=event.at,
                            service=self.service,
                            release=self.release_name,
                            request_id=event.request_id,
                            session_id=event.session_id,
                        )
                    )
            await db.commit()


def install_error_capture(
    service: str, maker: async_sessionmaker[AsyncSession], *, release: str | None = None
) -> ErrorCapture:
    """Add an ErrorCapture to the root logger, replacing one installed before."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, ErrorCapture):
            root.removeHandler(handler)
    capture = ErrorCapture(service, maker, release=release)
    root.addHandler(capture)
    return capture


def uninstall_error_capture(capture: ErrorCapture) -> None:
    logging.getLogger().removeHandler(capture)
