"""v2 part 2 core changes (C2): stories (ST-1, ST-5, ST-6) and delivery metrics (DM-1)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from strong_core.db.models import USER_OWNED_TABLES, Base
from strong_core.schemas import (
    Competency,
    DeliveryMetrics,
    QuestionScore,
    Scorecard,
    Story,
    StoryFit,
    StoryFitItem,
    StoryFitStrength,
    StoryPart,
    StorySource,
    StoryStatus,
)

FIXTURES = Path(__file__).parents[1] / "src" / "strong_core" / "gateway" / "fixtures"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _story(**extra: object) -> Story:
    return Story.model_validate(
        {
            "id": str(uuid.uuid4()),
            "title": "Checkout migration",
            "source": "manual",
            "created_at": NOW,
            "updated_at": NOW,
            **extra,
        }
    )


def test_st1_stories_table_is_user_owned_with_org_id() -> None:
    """ST-1: stories are user-owned: a non-null org_id foreign key, and a user_id."""
    assert "stories" in USER_OWNED_TABLES
    columns = Base.metadata.tables["stories"].columns
    assert not columns["org_id"].nullable and columns["org_id"].foreign_keys
    assert not columns["user_id"].nullable and columns["user_id"].foreign_keys


def test_st1_stories_table_has_the_five_parts_status_and_source() -> None:
    """ST-1: one nullable text column per StoryPart; status defaults to draft."""
    columns = Base.metadata.tables["stories"].columns
    for part in StoryPart:
        assert columns[part.value].nullable, part
    assert str(columns["status"].server_default.arg) == StoryStatus.DRAFT
    for name in ("source", "source_session_id", "source_question_ref", "notes_json", "skills"):
        assert name in columns


def test_st1_story_contract_defaults_and_parts() -> None:
    """ST-1: a story needs only a title and a source; it starts as a draft with no parts."""
    story = _story(action="I wrote the rollback plan.", skills=["ownership"])
    assert story.status == StoryStatus.DRAFT
    assert story.source == StorySource.MANUAL
    assert story.skills == [Competency.OWNERSHIP]
    assert story.part(StoryPart.ACTION) == "I wrote the rollback plan."
    assert story.part(StoryPart.CONTEXT) is None
    assert [p.value for p in StoryPart] == ["context", "stakes", "action", "result", "reflection"]


def test_st1_story_contract_rejects_bad_input() -> None:
    """ST-1: unknown fields, an empty title, unknown skills, repeated skills and unknown
    sources are rejected."""
    for bad in (
        {"rating": 5},
        {"title": ""},
        {"skills": ["vibes"]},
        {"skills": ["ownership", "ownership"]},
        {"source": "import"},
        {"status": "great"},
    ):
        with pytest.raises(ValidationError):
            _story(**bad)


def test_st6_story_notes_round_trip() -> None:
    """ST-6: a debrief's fix note keeps its session ref and date."""
    session_id = uuid.uuid4()
    story = _story(
        notes=[{"text": "Say the result in numbers.", "session_id": str(session_id), "at": NOW}]
    )
    assert story.notes[0].session_id == session_id
    assert Story.model_validate_json(story.model_dump_json()) == story


def test_st6_question_score_story_fields_are_optional() -> None:
    """ST-6: per-question story_id and story_fix default to null, so old scorecards load."""
    base = {
        "question_ref": "q1",
        "question_text": "Tell me about a time...",
        "scores": [
            {
                "competency": "ownership",
                "score": 3,
                "justification": "Clear ownership.",
                "quotes": ["I owned it."],
            }
        ],
    }
    old = QuestionScore.model_validate(base)
    assert old.story_id is None and old.story_fix is None and old.delivery is None
    story_id = uuid.uuid4()
    new = QuestionScore.model_validate(
        {**base, "story_id": str(story_id), "story_fix": "Add the result."}
    )
    assert new.story_id == story_id


def test_st5_story_fit_fixture_validates() -> None:
    """ST-5: the planner's fake StoryFit reply validates and covers all three strengths."""
    raw = json.loads((FIXTURES / "planner" / "StoryFit.json").read_text("utf-8"))
    fit = StoryFit.model_validate(raw)
    assert {i.strength for i in fit.items} == set(StoryFitStrength)


def test_st5_story_fit_item_story_id_matches_strength() -> None:
    """ST-5: story_id is null exactly when the strength is missing; one item per skill."""
    item = {"competency": "ownership", "reason": "Because."}
    StoryFitItem.model_validate({**item, "story_id": None, "strength": "missing"})
    with pytest.raises(ValidationError):
        StoryFitItem.model_validate({**item, "story_id": None, "strength": "strong"})
    with pytest.raises(ValidationError):
        StoryFitItem.model_validate({**item, "story_id": str(uuid.uuid4()), "strength": "missing"})
    missing = {**item, "story_id": None, "strength": "missing"}
    with pytest.raises(ValidationError):
        StoryFit.model_validate({"items": [missing, missing]})


def test_dm1_delivery_metrics_on_per_question_scores() -> None:
    """DM-1: delivery metrics per answer, stored in the scorecard's per-question data."""
    raw = json.loads((FIXTURES / "scorer" / "Scorecard.json").read_text("utf-8"))
    raw["per_question"][0]["delivery"] = {
        "words_per_minute": 142.5,
        "fillers_per_minute": 3.2,
        "duration_seconds": 95,
    }
    card = Scorecard.model_validate(raw)
    assert card.per_question[0].delivery == DeliveryMetrics(
        words_per_minute=142.5, fillers_per_minute=3.2, duration_seconds=95
    )
    with pytest.raises(ValidationError):
        DeliveryMetrics(words_per_minute=-1, fillers_per_minute=0, duration_seconds=1)
    with pytest.raises(ValidationError):
        DeliveryMetrics.model_validate(
            {"words_per_minute": 1, "fillers_per_minute": 0, "duration_seconds": 1, "audio": "x"}
        )
