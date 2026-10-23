"""strong_core.ops: heartbeats (OB-1), error capture (OB-4), log lines (OB-7) and the speech
hosted equivalent and server share (D-12, OB-15)."""

from __future__ import annotations

import fnmatch
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.db.models import Base, ErrorEvent, ErrorGroup, InterviewSession
from strong_core.gateway import usage_context
from strong_core.ops import heartbeat as hb
from strong_core.ops.costs import Usage, hosted_equivalent_usd, server_share_per_session
from strong_core.ops.errors import ErrorCapture, describe, scrub_message, scrub_stack
from strong_core.ops.logs import ContextFilter, JsonFormatter, log_context
from strong_core.schemas.enums import (
    Difficulty,
    ErrorGroupStatus,
    InterviewType,
    Mode,
    SessionStatus,
)

Maker = async_sessionmaker[AsyncSession]


class FakeRedis:
    """The few redis.asyncio calls the heartbeat uses, in memory (TTL kept, not enforced)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}
        self.fail = False

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        self.data[name], self.ttl[name] = value, ex
        return True

    async def delete(self, *names: str) -> int:
        return sum(self.data.pop(n, None) is not None for n in names)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.data.get(k) for k in keys]

    async def scan_iter(self, match: str | None = None, count: int | None = None) -> Any:
        for key in list(self.data):
            if match is None or fnmatch.fnmatch(key, match):
                yield key.encode()


# ---------------------------------------------------------------------------------- OB-1


async def test_ob1_heartbeat_key_value_and_ttl() -> None:
    redis = FakeRedis()
    beat = hb.Heartbeat(redis, "worker", model_profile="local", instance="box-7")
    assert await beat.beat()
    assert beat.key == "heartbeat:worker:box-7"
    assert redis.ttl[beat.key] == 60 and hb.INTERVAL_S == 15
    value = json.loads(redis.data[beat.key])
    assert set(value) == {"service", "instance", "version", "model_profile", "started_at", "at"}
    assert value["service"] == "worker" and value["model_profile"] == "local"

    await hb.Heartbeat(redis, "api", model_profile="local", instance="a1").beat()
    assert await hb.service_up(redis, "worker") and not await hb.service_up(redis, "voice")
    services = {b["service"] for b in await hb.read_heartbeats(redis)}
    assert services == {"api", "worker"}

    beat.start()
    await beat.stop()  # a clean stop removes the key at once
    assert not await hb.service_up(redis, "worker")


async def test_ob1_heartbeat_never_raises_when_redis_is_down() -> None:
    redis = FakeRedis()
    redis.fail = True
    beat = hb.Heartbeat(redis, "voice", model_profile="fake")
    assert await beat.beat() is False
    assert ":" not in beat.instance


# ---------------------------------------------------------------------------------- OB-4


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables[t] for t in ("error_groups", "error_events")]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


RESUME = """Jane Candidate
jane.candidate@example.com | +1 (425) 555-0100 | https://example.com/cv?token=abc123
Staff engineer who led the payments ledger migration across four regions.
Mentored nine engineers and cut incident volume by half."""


def _raise_parse_error() -> None:
    raise ValueError(f"could not parse resume: {RESUME}")


def _record(logger: str = "strong_worker.inputs", msg: str = "parse failed", **kw: Any) -> Any:
    args = kw.pop("args", ())
    return logging.LogRecord(
        logger, logging.ERROR, __file__, 1, msg, args, kw.pop("exc_info", None), **kw
    )


def _exc_record() -> logging.LogRecord:
    try:
        _raise_parse_error()
    except ValueError:
        return _record(exc_info=sys.exc_info())
    raise AssertionError


def test_ob4_scrubbing_keeps_no_resume_text_email_phone_or_query() -> None:
    message = scrub_message(f"could not parse resume: {RESUME}")
    assert "Jane Candidate" in message  # the first line, cut to a few words
    assert "example.com" not in message and "Mentored" not in message
    assert "[text removed]" in message
    assert scrub_message("mail ana@example.com now") == "mail [email] now"
    assert scrub_message("call +1 425 555 0100") == "call [phone]"
    assert scrub_message("GET https://x.test/a?email=b%40c.d") == "GET https://x.test/a?[query]"


async def test_ob4_a_resume_body_in_an_exception_never_reaches_stored_rows(maker: Maker) -> None:
    """The L05 rule: no resume or transcript text, email, phone or URL query in error rows."""
    capture = ErrorCapture("worker", maker)
    capture.emit(_exc_record())
    assert await capture.write_pending() == 1
    async with maker() as db:
        group = (await db.scalars(select(ErrorGroup))).one()
        dump = " ".join(
            str(v) for v in (await db.execute(text("SELECT * FROM error_groups"))).one()
        )
        dump += " ".join(
            str(v) for v in (await db.execute(text("SELECT * FROM error_events"))).one()
        )
    for secret in ("jane.candidate@example.com", "555-0100", "token=abc123", "payments ledger"):
        assert secret not in dump, secret
    assert group.exception_type == "ValueError" and group.service == "worker"
    assert group.sample_stack and "_raise_parse_error" in group.sample_stack
    assert group.status == ErrorGroupStatus.OPEN and group.count == 1


def test_ob4_fingerprint_is_type_and_top_frames_not_the_message() -> None:
    first, second = describe(_exc_record()), describe(_exc_record())
    assert first.fingerprint == second.fingerprint and len(first.fingerprint) == 64
    log_a = describe(_record(msg="job %s failed after %d s", args=("a1", 3)))
    log_b = describe(_record(msg="job %s failed after %d s", args=("b2", 9)))
    other = describe(
        _record(logger="strong_api.auth", msg="job %s failed after %d s", args=("a", 1))
    )
    assert log_a.fingerprint == log_b.fingerprint != other.fingerprint
    assert log_a.exception_type == "log:strong_worker.inputs"
    assert log_a.stack is None and log_a.message == "job a1 failed after 3 s"


def test_ob4_forwarded_records_are_parsed_from_their_text() -> None:
    """Voice job processes forward records with the stack already formatted."""
    stack = (
        "Traceback (most recent call last):\n"
        '  File "/app/apps/voice/src/strong_voice/interview_agent.py", line 10, in run_session\n'
        "    await interview.opening()\n"
        "RuntimeError: room closed for jane@example.com\n"
        "second line of a transcript the candidate said\n"
    )
    record = _record(logger="strong_voice", msg="job failed\n" + stack)
    record.exc_text = stack
    record.room = "session-" + str(uuid.UUID(int=7))
    info = describe(record)
    assert info.exception_type == "RuntimeError"
    assert info.session_id == uuid.UUID(int=7)
    assert info.stack and "jane@example.com" not in info.stack and "transcript" not in info.stack
    assert "strong_voice/interview_agent.py" in info.stack
    assert "[email]" in scrub_stack(stack)


async def test_ob4_rate_limit_one_event_per_10_s_and_the_count_still_goes_up(
    maker: Maker,
) -> None:
    now = [0.0]
    capture = ErrorCapture("api", maker, clock=lambda: now[0])
    for _ in range(5):
        capture.emit(_exc_record())
    now[0] = 11.0
    capture.emit(_exc_record())
    await capture.write_pending()
    async with maker() as db:
        group = (await db.scalars(select(ErrorGroup))).one()
        events = list(await db.scalars(select(ErrorEvent)))
    assert group.count == 6 and len(events) == 2


async def test_ob4_a_resolved_group_reopens_and_counts_add_up(maker: Maker) -> None:
    capture = ErrorCapture("api", maker)
    capture.emit(_exc_record())
    await capture.write_pending()
    async with maker() as db:
        group = (await db.scalars(select(ErrorGroup))).one()
        group.status = ErrorGroupStatus.RESOLVED
        group.resolved_at = datetime.now(UTC)
        await db.commit()
    capture.emit(_exc_record())
    await capture.write_pending()
    async with maker() as db:
        group = (await db.scalars(select(ErrorGroup))).one()
    assert group.count == 2 and group.status == ErrorGroupStatus.OPEN
    assert group.resolved_at is None


async def test_ob4_handler_never_raises_and_skips_its_own_logger() -> None:
    def broken() -> Any:
        raise RuntimeError("no database")

    capture = ErrorCapture("api", broken)  # type: ignore[arg-type]
    capture.emit(_record(logger="strong_core.ops.errors"))
    assert capture._pending == {}
    capture.emit(_exc_record())
    assert await capture.write_pending() == 0  # logged as a warning, not raised
    capture.emit(_record(msg="%s %s", args=("one",)))  # a bad format string: dropped quietly
    assert capture.dropped == 1


# ---------------------------------------------------------------------------------- OB-7


def test_ob7_json_line_has_service_request_and_session_ids() -> None:
    sid = uuid.uuid4()
    record = _record(msg="turn %d saved", args=(3,))
    with log_context(request_id="req-1"), usage_context(uuid.uuid4(), session_id=sid):
        ContextFilter().filter(record)
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "turn 3 saved" and line["level"] == "ERROR"
    assert line["request_id"] == "req-1" and line["session_id"] == str(sid)
    assert line["service"]


# ---------------------------------------------------------------------------- D-12, OB-15


def test_d12_hosted_equivalent_counts_self_hosted_speech_only() -> None:
    rows = [
        Usage("stt", Decimal(100), cost_known=False),  # 100 s x $0.0001
        Usage("tts", Decimal(1000), cost_known=False),  # 1000 characters x $0.000015
        Usage("stt", Decimal(50), cost_known=True),  # a metered provider: already in the cost
        Usage("interviewer", Decimal(5000), cost_known=False),
    ]
    assert hosted_equivalent_usd(rows, "local") == Decimal("0.025000")
    assert hosted_equivalent_usd(rows, "fake") == Decimal(0)  # no config, no shadow price


async def test_ob15_server_share_is_infra_cost_over_completed_sessions() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["sessions"]])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        for status, ended in (
            (SessionStatus.COMPLETED, datetime(2026, 10, 3, tzinfo=UTC)),
            (SessionStatus.COMPLETED, datetime(2026, 10, 30, tzinfo=UTC)),
            (SessionStatus.FAILED, datetime(2026, 10, 4, tzinfo=UTC)),
            (SessionStatus.COMPLETED, datetime(2026, 11, 1, tzinfo=UTC)),
        ):
            db.add(
                InterviewSession(
                    org_id=uuid.uuid4(),
                    job_target_id=uuid.uuid4(),
                    type=InterviewType.BEHAVIORAL,
                    difficulty=Difficulty.REALISTIC,
                    mode=Mode.REALISTIC,
                    duration_min=30,
                    status=status,
                    ended_at=ended,
                )
            )
        await db.commit()
        share = await server_share_per_session(db, date(2026, 10, 1), infra_monthly_usd=50.0)
        none_set = await server_share_per_session(db, date(2026, 10, 1), infra_monthly_usd=0)
        empty = await server_share_per_session(db, date(2026, 9, 1), infra_monthly_usd=50.0)
    await engine.dispose()
    assert share == 25.0 and none_set is None and empty is None
