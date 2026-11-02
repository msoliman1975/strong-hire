"""Deep story crafting in the worker (SC03): a styled story is reviewed on its sections with
review v2, as notes only (ST-11 with SC-14); a classic story keeps review v1 and its edits."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from strong_core.config import find_repo_root
from strong_core.gateway import FakeBackend, ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import Story, StorySource
from strong_worker.suggestions import generate

FIXTURES = find_repo_root() / "packages/core/src/strong_core/gateway/fixtures/coach"
NOW = datetime(2026, 11, 2, tzinfo=UTC)
WORDS = "We were done a week before Black Friday and not one payment failed."


def _story(**extra: Any) -> Story:
    return Story.model_validate(
        {
            "id": str(uuid.uuid4()),
            "title": "Checkout migration",
            "context": WORDS,
            "result": "The migration went well.",
            "source": StorySource.MANUAL.value,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
            **extra,
        }
    )


def _gateway() -> ModelGateway:
    return ModelGateway(fake_models_config(), fake=FakeBackend())


async def test_st11_sc14_a_styled_story_is_reviewed_on_its_sections_without_edits() -> None:
    """ST-11, SC-14: review v2 sees the sections and slots; its notes keep no edit, because a
    styled story's parts are rendered from the outline (the user improves a section instead)."""
    outline = json.loads((FIXTURES / "OrganizeResult.json").read_text("utf-8"))["outline"]
    styled = _story(style="star", outline=outline)
    written = await generate.review_story(_gateway(), styled, [WORDS])
    assert written.output is not None and written.output.notes
    assert all(n.edit is None for n in written.output.notes)
    rendered = generate.render_sections(styled)
    assert "situation:" in rendered and "step 1 did:" in rendered
    assert "constraints: (empty)" in rendered


async def test_st11_a_classic_story_keeps_review_v1_and_its_edits() -> None:
    """ST-11: a classic story is reviewed with v1, and an edit from the user's words stays."""
    written = await generate.review_story(_gateway(), _story(), [WORDS])
    assert written.output is not None
    result = next(n for n in written.output.notes if n.part.value == "result")
    assert result.edit is not None
    from strong_core.prompts import load_prompt

    v1 = load_prompt("coach", "review", version=1).render()
    v2 = load_prompt("coach", "review", version=2).render()
    assert "sections" in v2 and "Improve with Strova" in v2
    assert "sections" not in v1
