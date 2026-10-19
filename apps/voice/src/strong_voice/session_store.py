"""Database and API access for voice interview sessions (P7).

load_session      the session row, its brief and the facts the interviewer may use
SqlSessionStore   saves turns (text only) and provenance
SqlTimingStore    saves per-turn latency to voice_turn_timings, in the background (OB-3)
ApiFinisher       asks the API to end the session: bill the minutes, start scoring

Usage (tokens, audio seconds, characters) is not written here: the gateway writes one
usage_events row per model call inside the session's usage context (OB-2).
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass, field

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget, VoiceTurnTiming
from strong_core.db.models import Turn as TurnRow
from strong_core.db.turns import next_turn_seq
from strong_core.schemas import InterviewerBrief, JobPosting, Turn
from strong_interview import SessionFacts
from strong_voice.latency import TurnLatency

log = logging.getLogger(__name__)

SESSION_ROOM_PREFIX = "session-"


class AgentApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_internal_url: str = Field(
        default="http://api:8000", description="The API, as the voice agent reaches it."
    )
    strong_internal_token: str = Field(
        default="dev-internal-token",
        description="Shared secret for /internal endpoints. Set a long random value in production.",
    )


def session_id_from_room(room: str) -> uuid.UUID | None:
    if not room.startswith(SESSION_ROOM_PREFIX):
        return None
    try:
        return uuid.UUID(room.removeprefix(SESSION_ROOM_PREFIX))
    except ValueError:
        return None


@dataclass
class LoadedSession:
    id: uuid.UUID
    org_id: uuid.UUID
    brief: InterviewerBrief
    facts: SessionFacts


async def load_session(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> LoadedSession | None:
    """The session and its brief. None if it does not exist, has no brief, or has ended."""
    async with maker() as db:
        row = await db.get(InterviewSession, session_id)
        if row is None or row.brief_json is None or row.ended_at is not None:
            return None
        brief = InterviewerBrief.model_validate(row.brief_json)
        facts = SessionFacts(company_name=brief.company_name)
        target = await db.get(JobTarget, row.job_target_id)
        if target is not None and target.parsed_json is not None:
            posting = JobPosting.model_validate(target.parsed_json)
            facts = SessionFacts(
                company_name=brief.company_name or posting.company_name,
                job_title=posting.title,
                team=posting.team,
                notes=tuple(posting.responsibilities[:5]),
            )
        return LoadedSession(id=row.id, org_id=row.org_id, brief=brief, facts=facts)


async def session_org(
    maker: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> uuid.UUID | None:
    """The org of a session, for its usage context (OB-2). None when unknown or on error."""
    try:
        async with maker() as db:
            row = await db.get(InterviewSession, session_id)
            return row.org_id if row is not None else None
    except Exception:
        log.warning("could not read the org of session %s", session_id, exc_info=True)
        return None


@dataclass
class SqlSessionStore:
    maker: async_sessionmaker[AsyncSession]
    org_id: uuid.UUID

    async def save_turn(self, session_id: uuid.UUID, turn: Turn) -> None:
        async with self.maker() as db:
            db.add(
                TurnRow(
                    org_id=self.org_id,
                    session_id=session_id,
                    speaker=turn.speaker,
                    phase=turn.phase,
                    text=turn.text,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    question_ref=turn.question_ref,
                    seq=await next_turn_seq(db, session_id),
                )
            )
            await db.commit()

    async def save_provenance(self, session_id: uuid.UUID, prompt_version: str | None) -> None:
        async with self.maker() as db:
            await db.execute(
                update(InterviewSession)
                .where(InterviewSession.id == session_id)
                .values(prompt_version=prompt_version)
            )
            await db.commit()


def _ms(value: float) -> int | None:
    return None if value is None or math.isnan(value) else round(value)


@dataclass
class SqlTimingStore:
    """OB-3: per-turn latency rows. add() never waits on the database: rows are written in a
    background task every FLUSH_EVERY turns, and the rest by flush() when the session ends."""

    maker: async_sessionmaker[AsyncSession]
    org_id: uuid.UUID
    session_id: uuid.UUID
    flush_every: int = 5
    pending: list[TurnLatency] = field(default_factory=list)
    _tasks: set[asyncio.Task[int]] = field(default_factory=set)

    def add(self, turn: TurnLatency) -> None:
        self.pending.append(turn)
        if len(self.pending) >= self.flush_every:
            rows, self.pending = self.pending, []
            task = asyncio.create_task(self._write(rows))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def flush(self) -> int:
        """Write the pending rows in one insert. Never raises (the rows are only lost)."""
        rows, self.pending = self.pending, []
        return await self._write(rows)

    async def _write(self, rows: list[TurnLatency]) -> int:
        if not rows:
            return 0
        try:
            async with self.maker() as db:
                db.add_all(
                    VoiceTurnTiming(
                        org_id=self.org_id,
                        session_id=self.session_id,
                        turn_index=t.turn,
                        e2e_ms=_ms(t.total_ms),
                        turn_detection_ms=_ms(t.turn_detection_ms),
                        stt_ms=_ms(t.stt_ms),
                        llm_ttft_ms=_ms(t.llm_ttft_ms),
                        tts_ttfb_ms=_ms(t.tts_ttfb_ms),
                        other_ms=_ms(t.other_ms),
                    )
                    for t in rows
                )
                await db.commit()
        except Exception:
            log.warning("could not save %d turn timings of %s", len(rows), self.session_id)
            return 0
        return len(rows)

    async def close(self) -> None:
        """Wait for background writes, then write the rest (the session ended)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.flush()


@dataclass
class ApiFinisher:
    settings: AgentApiSettings

    async def finish(self, session_id: uuid.UUID, *, interrupted: bool) -> None:
        async with httpx.AsyncClient(base_url=self.settings.api_internal_url, timeout=15) as http:
            resp = await http.post(
                f"/internal/sessions/{session_id}/end",
                json={"interrupted": interrupted},
                headers={"X-Internal-Token": self.settings.strong_internal_token},
            )
            resp.raise_for_status()
