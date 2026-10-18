"""What api, worker and voice start at boot and stop at shutdown (admin spec OB-1, OB-2, OB-4).

    ops = await start_ops("worker", redis=ctx["redis"])
    ...
    await ops.stop()

start_ops installs the database usage sink (every gateway call inside a usage context writes a
usage_events row, OB-2), the error capture handler and its writer task (OB-4), and the Redis
heartbeat (OB-1). Each part is optional and none of them raises: a service whose Redis or
database is down still starts, and says so in its logs.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any

from strong_core.config import get_settings
from strong_core.gateway.usage import make_db_usage_sink, set_usage_sink
from strong_core.ops.errors import ErrorCapture, install_error_capture, uninstall_error_capture
from strong_core.ops.heartbeat import Heartbeat

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)


@dataclass
class OpsRuntime:
    service: str
    errors: ErrorCapture | None = None
    heartbeat: Heartbeat | None = None
    _owned_redis: Any | None = None
    _previous_hook: Any | None = None

    async def stop(self) -> None:
        if self.heartbeat is not None:
            await self.heartbeat.stop()
        if self.errors is not None:
            await self.errors.stop()
            uninstall_error_capture(self.errors)
        if self._previous_hook is not None:
            sys.excepthook = self._previous_hook
        if self._owned_redis is not None:
            with contextlib.suppress(Exception):
                await self._owned_redis.aclose()


def _excepthook(previous: Any) -> Any:
    """Log an uncaught exception at ERROR (so it is captured), then run the previous hook."""

    def hook(exc_type: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            logging.getLogger("strong.unhandled").error(
                "unhandled exception", exc_info=(exc_type, value, tb)
            )
        previous(exc_type, value, tb)

    return hook


async def start_ops(
    service: str,
    *,
    maker: async_sessionmaker[AsyncSession] | None = None,
    redis: Any | None = None,
    heartbeat: bool = True,
    capture_errors: bool = True,
    usage_sink: bool = True,
    model_profile: str | None = None,
) -> OpsRuntime:
    settings = get_settings()
    if maker is None and (capture_errors or usage_sink):
        from strong_core.db import get_sessionmaker

        maker = get_sessionmaker()
    runtime = OpsRuntime(service)
    if usage_sink and maker is not None:
        set_usage_sink(make_db_usage_sink(maker))
    if capture_errors and maker is not None:
        runtime.errors = install_error_capture(service, maker)
        runtime.errors.start()
        runtime._previous_hook = sys.excepthook
        sys.excepthook = _excepthook(sys.excepthook)
    if heartbeat:
        if redis is None:
            from redis.asyncio import Redis

            redis = runtime._owned_redis = Redis.from_url(settings.redis_url)
        runtime.heartbeat = Heartbeat(
            redis, service, model_profile=model_profile or settings.model_profile.value
        )
        runtime.heartbeat.start()
    log.info(
        "ops started for %s: heartbeat=%s errors=%s usage=%s",
        service,
        heartbeat,
        capture_errors,
        usage_sink,
    )
    return runtime
