"""v2 part 3 core changes (C3): the coach role and its data (CO-1), Recruiter screen (RS-1)
and the readiness contract (RD-1)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core.config import Settings
from strong_core.db.models import USER_OWNED_TABLES, Base
from strong_core.gateway import Message, Role, build_gateway, load_models_config
from strong_core.gateway.types import CHAT_ROLES
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    CoachReply,
    CoachSessionStatus,
    CoachStyle,
    Competency,
    InterviewType,
    Readiness,
    ReadinessStatus,
    SessionConfig,
    SkillReadiness,
    StoryPart,
    StoryVersions,
    session_competencies,
)

CONFIG = Path(__file__).parents[3] / "config"
FIXTURES = Path(__file__).parents[1] / "src" / "strong_core" / "gateway" / "fixtures"
PROFILES = sorted(p.stem.removeprefix("models.") for p in CONFIG.glob("models.*.yaml"))


def test_co1_coach_is_a_chat_role_mapped_in_every_profile() -> None:
    """CO-1: coach is a gateway chat role, mapped in every config/models.*.yaml to an alias
    the profile already uses, so no new model id is needed."""
    assert Role.COACH in CHAT_ROLES
    assert PROFILES
    for profile in PROFILES:
        cfg = load_models_config(CONFIG, profile, environ={})
        alias = cfg.alias_for(Role.COACH)
        assert alias in {cfg.alias_for(r) for r in CHAT_ROLES - {Role.COACH}}, profile
        assert cfg.capabilities(Role.COACH).json_mode, profile


async def test_co1_fake_coach_returns_its_fixtures() -> None:
    """CO-1: the fake coach answers with the CoachReply and StoryVersions fixtures."""
    gw = build_gateway(Settings(model_profile="fake"))
    messages = [Message(role="user", content="I moved checkout to a new provider.")]
    reply = await gw.complete(Role.COACH, messages, output_type=CoachReply)
    assert reply.output.message and reply.output.parts
    versions = await gw.complete(Role.COACH, messages, output_type=StoryVersions)
    assert versions.output.sixty_second.quotes and versions.output.full.quotes


def test_co3_coach_reply_fixture_keeps_parts_and_missing_apart() -> None:
    """CO-3, CO-9: each updated part carries the candidate's quotes; missing parts are listed."""
    raw = (FIXTURES / "coach" / "CoachReply.json").read_text("utf-8")
    reply = CoachReply.model_validate_json(raw)
    updated = {p.part for p in reply.parts}
    assert updated.isdisjoint(reply.missing)
    assert updated | set(reply.missing) == set(StoryPart)
    assert all(p.quotes for p in reply.parts)


def test_co3_coach_reply_rejects_bad_input() -> None:
    """CO-3: unknown fields, repeated parts, a part both updated and missing, and parts
    without quotes are rejected."""
    part = {"part": "action", "text": "I wrote the plan.", "quotes": ["I wrote the plan"]}
    ok = {"message": "What happened next?", "parts": [part], "missing": ["result"]}
    CoachReply.model_validate(ok)
    for bad in (
        {**ok, "tone": "warm"},
        {**ok, "parts": [part, part]},
        {**ok, "missing": ["action"]},
        {**ok, "missing": ["result", "result"]},
        {**ok, "skills": ["ownership", "ownership"]},
        {**ok, "parts": [{**part, "quotes": []}]},
        {**ok, "message": ""},
    ):
        with pytest.raises(ValidationError):
            CoachReply.model_validate(bad)


def test_co8_story_versions_need_quotes() -> None:
    """CO-8: both versions are built from the candidate's words, so each carries quotes."""
    raw = json.loads((FIXTURES / "coach" / "StoryVersions.json").read_text("utf-8"))
    StoryVersions.model_validate(raw)
    raw["full"]["quotes"] = []
    with pytest.raises(ValidationError):
        StoryVersions.model_validate(raw)


@pytest.mark.parametrize("table", ["coach_sessions", "coach_turns", "takes"])
def test_co1_coach_tables_are_user_owned(table: str) -> None:
    """CO-2, CO-7: coach sessions, coach turns and takes are user-owned with org_id."""
    assert table in USER_OWNED_TABLES
    org_id = Base.metadata.tables[table].columns["org_id"]
    assert not org_id.nullable and org_id.foreign_keys


def test_co1_coach_session_turn_and_take_columns() -> None:
    """CO-2, CO-5, CO-6, CO-7: style, channel, status, minutes and PL-6 provenance."""
    sessions = Base.metadata.tables["coach_sessions"].columns
    turns = Base.metadata.tables["coach_turns"].columns
    takes = Base.metadata.tables["takes"].columns
    provenance = ("model_profile", "model_id", "prompt_version")
    for name in ("user_id", "story_id", "style", "channel", "status", "minutes", *provenance):
        assert name in sessions, name
    assert str(sessions["status"].server_default.arg) == CoachSessionStatus.ACTIVE
    assert [s.value for s in CoachStyle] == ["gentle", "direct"]
    for name in ("coach_session_id", "seq", "speaker", "text", "start_ms", "end_ms"):
        assert name in turns, name
    take_columns = ("user_id", "story_id", "channel", "text", "duration_s", "skill_scores_json")
    for name in (*take_columns, *provenance):
        assert name in takes, name
    assert not takes["story_id"].nullable


def test_rs1_recruiter_screen_has_its_own_competencies() -> None:
    """RS-1: Recruiter screen is a fifth interview type scored on motivation, role fit,
    communication, and logistics and expectations. It is not a Custom category."""
    config = SessionConfig.model_validate(
        {
            "interview_type": "recruiter_screen",
            "difficulty": "realistic",
            "mode": "realistic",
            "duration_min": 30,
            "level": "mid",
        }
    )
    assert session_competencies(config) == (
        Competency.MOTIVATION,
        Competency.ROLE_FIT,
        Competency.COMMUNICATION,
        Competency.LOGISTICS_AND_EXPECTATIONS,
    )
    assert COMPETENCIES_BY_TYPE[InterviewType.RECRUITER_SCREEN] == session_competencies(config)
    assert InterviewType.RECRUITER_SCREEN not in STANDARD_INTERVIEW_TYPES
    assert "recruiter_screen" in Base.metadata.tables["sessions"].columns["type"].type.enums


def test_rd1_readiness_score_or_not_enough_data() -> None:
    """RD-1: per skill a 0 to 100 score or not_enough_data, sessions counted, an as-of date,
    labeled as a practice estimate."""
    readiness = Readiness.model_validate(
        {
            "job_target_id": str(uuid.uuid4()),
            "as_of": "2026-10-27",
            "skills": [
                {"competency": "ownership", "status": "scored", "score": 72, "sessions_counted": 3},
                {
                    "competency": "impact",
                    "status": "not_enough_data",
                    "score": None,
                    "sessions_counted": 0,
                },
            ],
        }
    )
    assert readiness.kind == "practice_estimate"
    assert readiness.as_of == date(2026, 10, 27)
    assert readiness.skills[1].status == ReadinessStatus.NOT_ENOUGH_DATA
    item = {"competency": "ownership", "sessions_counted": 1}
    for bad in (
        {**item, "status": "scored", "score": None},
        {**item, "status": "not_enough_data", "score": 10},
        {**item, "status": "scored", "score": 101},
        {**item, "status": "scored", "score": -1},
        {**item, "status": "scored", "score": 5, "sessions_counted": -1},
        {**item, "status": "scored", "score": 5, "trend": "up"},
    ):
        with pytest.raises(ValidationError):
            SkillReadiness.model_validate(bad)
    scored = {**item, "status": "scored", "score": 50}
    with pytest.raises(ValidationError):
        Readiness.model_validate(
            {"job_target_id": str(uuid.uuid4()), "as_of": "2026-10-27", "skills": [scored, scored]}
        )
