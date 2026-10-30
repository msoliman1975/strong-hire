"""UX with Strova core (U01): suggestions (SG-1), target interviews (RH-1), the plan style
(PS-2), the main resume (RM-2), and the plan, readiness and story idea contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core.db.models import USER_OWNED_TABLES, Base
from strong_core.schemas import (
    READINESS_GOAL,
    InterviewReadiness,
    Plan,
    PlanStyle,
    StoryIdea,
    StoryIdeas,
    StoryReview,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
)

MIGRATION = next(
    (Path(__file__).parents[1] / "migrations" / "versions").glob("*_0023_ux_strova_core.py")
)
NOW = datetime(2026, 10, 30, tzinfo=UTC)

PAYLOADS: dict[SuggestionKind, dict[str, object]] = {
    SuggestionKind.TUNE_STORY: {
        "kind": "tune_story",
        "edit": {"part": "result", "before": "It went well.", "after": "No payment failed."},
    },
    SuggestionKind.NEW_STORY: {"kind": "new_story", "title": "Checkout", "action": "I led it."},
    SuggestionKind.MISSING_SKILL: {"kind": "missing_skill", "competency": "conflict_handling"},
    SuggestionKind.TAILOR_ROLE: {"kind": "tailor_role", "company": "Stripe", "note": "Lead."},
    SuggestionKind.IMPROVE_RESUME_LINE: {
        "kind": "improve_resume_line",
        "resume_line_ref": "roles[0].achievements[1]",
        "before": "Led checkout migration",
        "after": "Led checkout migration with zero failed payments",
    },
    SuggestionKind.STORY_IDEA: {
        "kind": "story_idea",
        "achievement": "Led checkout migration",
        "skills": ["ownership"],
        "missing_parts": ["stakes"],
    },
    SuggestionKind.REVIEW: {
        "kind": "review",
        "review": {"summary": "Good.", "notes": [{"part": "result", "note": "Add the number."}]},
    },
}


def suggestion(kind: SuggestionKind, **extra: object) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "kind": kind.value,
        "payload": PAYLOADS[kind],
        "reason": "Your answer said it better than the story does.",
        "created_at": NOW.isoformat(),
        **extra,
    }


def test_sg1_suggestions_table_is_user_owned_with_the_spec_columns() -> None:
    """SG-1: one user-owned table with kind, status, source, target, payload and reason, in
    export and delete (USER_OWNED_TABLES feeds both, and org_id cascades)."""
    assert "suggestions" in USER_OWNED_TABLES
    table = Base.metadata.tables["suggestions"]
    for column in (
        "org_id",
        "user_id",
        "kind",
        "status",
        "source_session_id",
        "source_question_ref",
        "source_resume_id",
        "job_target_id",
        "story_id",
        "resume_id",
        "payload",
        "reason",
        "prompt_ref",
        "undo",
        "created_at",
        "resolved_at",
    ):
        assert column in table.columns, column
    assert not table.columns["org_id"].nullable
    assert not table.columns["user_id"].nullable
    org_fk = next(iter(table.columns["org_id"].foreign_keys))
    assert org_fk.ondelete == "CASCADE"
    assert any([c.name for c in ix.columns] == ["user_id", "status"] for ix in table.indexes), (
        "index on (user_id, status)"
    )


def test_sg1_every_kind_has_a_payload_contract() -> None:
    """SG-1: one payload model per kind; the payload kind must match the suggestion kind."""
    for kind in SuggestionKind:
        parsed = Suggestion.model_validate(suggestion(kind))
        assert parsed.payload.kind == kind.value
        assert parsed.status == SuggestionStatus.OPEN
    with pytest.raises(ValidationError):
        Suggestion.model_validate(
            suggestion(SuggestionKind.TUNE_STORY) | {"payload": PAYLOADS[SuggestionKind.REVIEW]}
        )


def test_sg1_suggestion_rejects_bad_input() -> None:
    """SG-1: unknown fields, a resolved_at on an open one, and a closed one without it fail."""
    ok = suggestion(SuggestionKind.MISSING_SKILL)
    resolved = {"status": "dismissed", "resolved_at": NOW.isoformat()}
    Suggestion.model_validate(ok | resolved)
    for bad in (
        ok | {"surprise": 1},
        ok | {"resolved_at": NOW.isoformat()},
        ok | {"status": "accepted"},
        ok | {"payload": {"kind": "missing_skill", "competency": "vibes"}},
        ok | {"reason": ""},
    ):
        with pytest.raises(ValidationError):
            Suggestion.model_validate(bad)


def test_sg1_resume_line_ref_and_review_edits_are_checked() -> None:
    """SG-6, ST-11: a resume line ref names a role achievement; a review edit matches its part."""
    line = suggestion(SuggestionKind.IMPROVE_RESUME_LINE)
    with pytest.raises(ValidationError):
        Suggestion.model_validate(
            line
            | {"payload": {**PAYLOADS[SuggestionKind.IMPROVE_RESUME_LINE], "resume_line_ref": "x"}}
        )
    edit = {"part": "action", "before": None, "after": "I did it."}
    with pytest.raises(ValidationError):
        StoryReview.model_validate(
            {"summary": "s", "notes": [{"part": "result", "note": "n", "edit": edit}]}
        )
    with pytest.raises(ValidationError):
        StoryReview.model_validate(
            {
                "summary": "s",
                "notes": [{"part": "result", "note": "a"}, {"part": "result", "note": "b"}],
            }
        )


def test_rm4_story_ideas_keep_skills_optional() -> None:
    """RM-4: a story idea still lists when the skills call failed (no skills)."""
    idea = StoryIdea.model_validate({"achievement": "Cut build time by half"})
    assert idea.skills == [] and idea.missing_parts == []
    assert StoryIdeas.model_validate({"items": [idea.model_dump()]}).items[0] == idea
    with pytest.raises(ValidationError):
        StoryIdea.model_validate({"achievement": "x", "skills": ["impact", "impact"]})


def test_rh1_target_interviews_table_is_role_resume_type() -> None:
    """RH-1: an interview is role x resume x type, user-owned, unique while not archived."""
    assert "target_interviews" in USER_OWNED_TABLES
    table = Base.metadata.tables["target_interviews"]
    for column in (
        "org_id",
        "user_id",
        "job_target_id",
        "resume_id",
        "interview_type",
        "custom_json",
        "created_at",
        "archived_at",
    ):
        assert column in table.columns, column
    for column in ("org_id", "user_id", "job_target_id", "resume_id", "interview_type"):
        assert not table.columns[column].nullable, column
    unique = next(ix for ix in table.indexes if ix.name == "uq_target_interviews_role_resume_type")
    assert unique.unique
    assert [c.name for c in unique.columns] == ["job_target_id", "resume_id", "interview_type"]
    assert "archived_at IS NULL" in str(unique.dialect_options["postgresql"]["where"])


def test_rh1_migration_backfills_interviews_from_sessions() -> None:
    """RH-1: the migration adds one interview per distinct (job, resume, type) in sessions."""
    text = MIGRATION.read_text("utf-8")
    assert "INSERT INTO target_interviews" in text
    assert "DISTINCT ON (s.job_target_id, s.resume_id, s.type)" in text


def test_rh2_interview_readiness_contract() -> None:
    """RH-2: score 0 to 100 or null, goal 75, per-competency scores out of 4, a practice
    estimate. No Realistic take means no score."""
    interview_id = str(uuid.uuid4())
    ok = InterviewReadiness.model_validate(
        {
            "interview_id": interview_id,
            "score": 58,
            "competencies": [
                {"competency": "ownership", "score": 3},
                {"competency": "impact", "score": None},
            ],
            "change": 6,
            "takes_counted": 2,
        }
    )
    assert ok.goal == READINESS_GOAL == 75
    assert ok.kind == "practice_estimate"
    empty = InterviewReadiness.model_validate({"interview_id": interview_id, "score": None})
    assert empty.takes_counted == 0
    for bad in (
        {"interview_id": interview_id, "score": 50},  # a score with no take counted
        {"interview_id": interview_id, "score": 101, "takes_counted": 1},
        {
            "interview_id": interview_id,
            "score": None,
            "competencies": [{"competency": "impact", "score": 5}],
        },
    ):
        with pytest.raises(ValidationError):
            InterviewReadiness.model_validate(bad)


def test_ps2_users_store_the_plan_style_and_email_mute() -> None:
    """PS-2, PS-6: users.plan_style (weekly or checklist, NULL until chosen) and
    users.plan_email_muted (default false)."""
    users = Base.metadata.tables["users"]
    style = users.columns["plan_style"]
    assert style.nullable
    assert set(style.type.enums) == {s.value for s in PlanStyle} == {"weekly", "checklist"}
    muted = users.columns["plan_email_muted"]
    assert not muted.nullable
    assert muted.server_default is not None and "false" in str(muted.server_default.arg)


def test_ps2_plan_contract() -> None:
    """PS-1, PS-2, PS-4: the plan carries its style; the weekly plan has one item per day."""
    item = {"kind": "story", "title": "Conflict handling: a Ready story", "status": "next"}
    plan = Plan.model_validate(
        {"style": "checklist", "items": [item | {"key": "a"}, item | {"key": "b"}]}
    )
    assert plan.style == PlanStyle.CHECKLIST
    monday = date(2026, 11, 2)
    with pytest.raises(ValidationError):
        Plan.model_validate(
            {
                "style": "weekly",
                "week_start": monday.isoformat(),
                "items": [
                    item | {"key": "a", "due": monday.isoformat()},
                    item | {"key": "b", "due": monday.isoformat()},
                ],
            }
        )
    with pytest.raises(ValidationError):
        Plan.model_validate({"style": "checklist", "items": [item | {"key": "a"}] * 2})


def test_rm2_one_main_resume_per_user() -> None:
    """RM-2: resumes.is_main (default false) with a partial unique index: at most one main
    among non-deleted resumes. The migration makes each user's newest resume main."""
    resumes = Base.metadata.tables["resumes"]
    is_main = resumes.columns["is_main"]
    assert not is_main.nullable
    assert "false" in str(is_main.server_default.arg)  # type: ignore[union-attr]
    index = next(ix for ix in resumes.indexes if ix.name == "uq_resumes_main_per_user")
    assert index.unique
    assert [c.name for c in index.columns] == ["user_id"]
    where = str(index.dialect_options["postgresql"]["where"])
    assert "is_main" in where and "deleted_at IS NULL" in where
    text = MIGRATION.read_text("utf-8")
    assert "UPDATE resumes SET is_main = true" in text
    assert "ORDER BY user_id, uploaded_at DESC" in text


def test_st13_story_answer_contract_and_fixture() -> None:
    """ST-13: Strova's answer on Career Stories names the stories it leans on and the user's
    words its facts came from; unknown fields are rejected."""
    from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
    from strong_core.schemas import StoryAnswer

    raw = (Path(DEFAULT_FIXTURES_DIR) / "coach" / "StoryAnswer.json").read_text(encoding="utf-8")
    answer = StoryAnswer.model_validate_json(raw)
    assert answer.answer and answer.quotes
    with pytest.raises(ValidationError):
        StoryAnswer.model_validate({"answer": ""})
    with pytest.raises(ValidationError):
        StoryAnswer.model_validate({"answer": "Yes.", "extra": 1})
