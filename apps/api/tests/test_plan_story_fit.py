"""ST-5: the plan page's story fit table (GET /plan/{job}/{resume}/story-fit)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from strong_api.plan import story_fit
from strong_core.schemas import Competency, StoryFit, StoryFitItem, StoryFitStrength
from strong_worker.gap import story_fit as worker_story_fit

from .conftest import InlineQueue
from .test_library_api import add_job, add_resume, other_client


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value


@pytest.fixture
def cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture
def queue(ctx: dict[str, Any], cache: MemoryCache) -> InlineQueue:
    """The inline queue, with the worker's story fit job and its Redis cache."""
    q = InlineQueue({**ctx, "redis": cache})
    real_enqueue = q.enqueue

    async def enqueue(function: str, job_id: str, **kwargs: Any) -> None:
        if function == story_fit.RUN_STORY_FIT:
            q.enqueued.append((function, job_id, kwargs))
            if q.run_jobs:
                q.results[job_id] = await worker_story_fit.run_story_fit(q.ctx, **kwargs)
            return
        await real_enqueue(function, job_id, **kwargs)

    q.enqueue = enqueue  # type: ignore[method-assign]
    return q


@pytest.fixture
def app_with_cache(app: FastAPI, cache: MemoryCache) -> FastAPI:
    app.state.story_fit_cache = cache
    return app


BEHAVIORAL_AND_HM = [
    "ownership",
    "impact",
    "collaboration",
    "conflict_handling",
    "learning_from_failure",
    "communication",
    "role_fit",
    "depth_of_experience",
    "judgment",
    "motivation",
    "team_fit",
    "scope_at_level",
]


def test_st5_keys_and_job_name_match_the_worker() -> None:
    """ST-5: the API reads the key the worker writes and enqueues the worker's function."""
    org, job = uuid.uuid4(), uuid.uuid4()
    assert story_fit.story_fit_key(org, job) == worker_story_fit.story_fit_key(org, job)
    assert story_fit.story_fit_job_id(org, job) == worker_story_fit.story_fit_job_id(org, job)
    assert story_fit.RUN_STORY_FIT in {f.__name__ for f in worker_story_fit.FUNCTIONS}


async def _pair(client: httpx.AsyncClient, fake_fixtures: Path) -> tuple[str, str]:
    job = await add_job(client, fake_fixtures)
    cv = await add_resume(client, fake_fixtures)
    return job["id"], cv["id"]


async def test_st5_story_fit_runs_the_worker_job_and_returns_one_row_per_story_skill(
    app_with_cache: FastAPI,
    client: httpx.AsyncClient,
    queue: InlineQueue,
    fake_fixtures: Path,
) -> None:
    """ST-5: each read enqueues run_story_fit with the tested story skills (generic mode: the
    behavioral and hiring manager rounds), and answers with the cached table, a row per skill."""
    job_id, cv_id = await _pair(client, fake_fixtures)
    made = await client.post("/stories", json={"title": "Payments outage", "skills": ["impact"]})
    assert made.status_code == 201, made.text

    resp = await client.get(f"/plan/{job_id}/{cv_id}/story-fit")
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert view["status"] == "ready"
    assert [r["competency"] for r in view["rows"]] == BEHAVIORAL_AND_HM
    # The default fake reply names no story of this user, so every skill is missing.
    assert {r["strength"] for r in view["rows"]} == {"missing"}
    assert all(r["story"] is None and r["reason"] for r in view["rows"])
    assert view["computed_at"]

    (_, job_key, kwargs), *_ = [e for e in queue.enqueued if e[0] == "run_story_fit"]
    assert job_key == story_fit.story_fit_job_id(kwargs["org_id"], job_id)
    assert kwargs["job_target_id"] == job_id
    assert kwargs["competencies"] == BEHAVIORAL_AND_HM


async def test_st5_shows_the_story_and_drops_deleted_ones(
    app_with_cache: FastAPI,
    client: httpx.AsyncClient,
    queue: InlineQueue,
    cache: MemoryCache,
    fake_fixtures: Path,
) -> None:
    """ST-5: a fitting story comes with its title and status; a story deleted since the table
    was computed shows as missing; a skill the table lacks keeps the view computing."""
    queue.run_jobs = False
    job_id, cv_id = await _pair(client, fake_fixtures)

    first = await client.get(f"/plan/{job_id}/{cv_id}/story-fit")
    assert first.json() == {"status": "computing", "rows": [], "computed_at": None}
    org_id = queue.enqueued[-1][2]["org_id"]

    story = (await client.post("/stories", json={"title": "Payments outage"})).json()
    items = [
        StoryFitItem(
            competency=Competency(c),
            story_id=uuid.UUID(story["id"]) if c == "ownership" else None,
            strength=StoryFitStrength.STRONG if c == "ownership" else StoryFitStrength.MISSING,
            reason="Shows it end to end." if c == "ownership" else "No story yet.",
        )
        for c in BEHAVIORAL_AND_HM
    ]
    items[1] = StoryFitItem(
        competency=Competency.IMPACT,
        story_id=uuid.uuid4(),
        strength=StoryFitStrength.THIN,
        reason="Some numbers.",
    )
    record = {
        "fit": StoryFit(items=items).model_dump(mode="json"),
        "input_hash": "h",
        "model_profile": "fake",
        "model_id": "fake-planner",
        "prompt_version": "planner/story_fit.v1",
        "computed_at": datetime.now(UTC).isoformat(),
    }
    key = story_fit.story_fit_key(org_id, job_id)
    cache.data[key] = json.dumps(record)

    view = (await client.get(f"/plan/{job_id}/{cv_id}/story-fit")).json()
    assert view["status"] == "ready"
    rows = {r["competency"]: r for r in view["rows"]}
    assert rows["ownership"]["strength"] == "strong"
    assert rows["ownership"]["story"] == {
        "id": story["id"],
        "title": "Payments outage",
        "status": "draft",
    }
    assert rows["impact"] == {
        "competency": "impact",
        "strength": "missing",
        "story": None,
        "reason": story_fit.DELETED_REASON,
    }

    record["fit"] = StoryFit(items=items[:3]).model_dump(mode="json")
    cache.data[key] = json.dumps(record)
    partial = (await client.get(f"/plan/{job_id}/{cv_id}/story-fit")).json()
    assert partial["status"] == "computing"
    assert len(partial["rows"]) == 3


async def test_st5_story_fit_is_owner_only(
    app_with_cache: FastAPI, client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    """ST-5: another user's job answers 404."""
    job_id, cv_id = await _pair(client, fake_fixtures)
    async with other_client(app_with_cache) as other:
        resp = await other.get(f"/plan/{job_id}/{cv_id}/story-fit")
    assert resp.status_code == 404
