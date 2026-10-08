"""Database and API access for voice interview sessions (P7).

load_session      the session row, its brief and the facts the interviewer may use
SqlSessionStore   saves turns (text only), usage units and provenance
ApiFinisher       asks the API to end the session: bill the minutes, start scoring
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import InterviewSession, JobTarget, UsageEvent
from strong_core.db.models import Turn as TurnRow
from strong_core.schemas import InterviewerBrief, JobPosting, Turn, UsageComponent
from strong_interview import SessionFacts

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
                )
            )
            await db.commit()

    async def save_usage(
        self, session_id: uuid.UUID, component: UsageComponent, units: float, cost_usd: float = 0.0
    ) -> None:
        # Units (tokens, seconds, characters). For LLM, cost_usd is the interviewer's cost from
        # the LiteLLM config prices (0 when unknown); speech has no cost here.
        async with self.maker() as db:
            db.add(
                UsageEvent(
                    org_id=self.org_id,
                    session_id=session_id,
                    component=component,
                    units=Decimal(str(units)),
                    cost_usd=Decimal(f"{cost_usd:.6f}"),
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
