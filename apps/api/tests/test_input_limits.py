"""Round 3 input limits: resume file size and count (IN-3), job description length (IN-1, IN-2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs import limits
from strong_core.config import get_settings
from strong_core.db.models import Resume as ResumeRow
from strong_worker.inputs import jobs
from strong_worker.inputs.jobs import CTX_KEY
from strong_worker.inputs.testing import make_fetcher, set_extractor_output

FIXTURES = get_settings().repo_root / "evals/fixtures/inputs"


def fixture(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    text = (FIXTURES / kind / f"{name}.txt").read_text(encoding="utf-8")
    return text, json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


def words(n: int) -> str:
    return " ".join(["word"] * n)


def test_in1_worker_word_limit_matches_the_api() -> None:
    assert jobs.MAX_POSTING_WORDS == limits.MAX_POSTING_WORDS
    assert jobs.POSTING_TOO_LONG_MESSAGE == limits.POSTING_TOO_LONG_MESSAGE


def test_in1_word_count_counts_runs_of_non_space() -> None:
    assert limits.word_count("  one\ttwo\n\nthree  ") == 3
    assert limits.word_count("") == 0


# --- resumes (IN-3) -------------------------------------------------------------------------


async def test_in3_resume_file_over_1_mb_is_413(client: httpx.AsyncClient) -> None:
    big = b"%PDF-" + b"0" * limits.MAX_RESUME_FILE_BYTES
    resp = await client.post("/resumes", files={"file": ("cv.pdf", big)})
    assert resp.status_code == 413
    assert resp.json()["detail"] == {
        "code": "file_too_large",
        "message": "The file is larger than 1 MB. Paste the resume text instead.",
    }


async def test_in3_resume_file_of_exactly_1_mb_is_accepted(
    client: httpx.AsyncClient, fake_fixtures: Path
) -> None:
    _, expected = fixture("resumes", "product-manager-mid")
    set_extractor_output(fake_fixtures, "Resume", expected)
    data = b"Jane Doe, engineer. " * (limits.MAX_RESUME_FILE_BYTES // 20)
    assert len(data) <= limits.MAX_RESUME_FILE_BYTES
    resp = await client.post("/resumes", files={"file": ("cv.txt", data)})
    assert resp.status_code == 202, resp.text


async def add_resume(client: httpx.AsyncClient) -> httpx.Response:
    text, _ = fixture("resumes", "product-manager-mid")
    return await client.post("/resumes", data={"text": text})


async def test_in3_sixth_resume_is_422(client: httpx.AsyncClient, fake_fixtures: Path) -> None:
    _, expected = fixture("resumes", "product-manager-mid")
    set_extractor_output(fake_fixtures, "Resume", expected)
    ids = []
    for _ in range(limits.MAX_RESUMES_PER_USER):
        resp = await add_resume(client)
        assert resp.status_code == 202, resp.text
        ids.append(resp.json()["resume"]["id"])

    sixth = await add_resume(client)
    assert sixth.status_code == 422
    assert sixth.json()["detail"] == {
        "code": "resume_limit",
        "message": "You can keep up to 5 resumes. Delete or replace one first.",
    }
    big = b"%PDF-" + b"0" * limits.MAX_RESUME_FILE_BYTES
    assert (await client.post("/resumes", files={"file": ("cv.pdf", big)})).status_code == 413

    # No replace endpoint: the client deletes one, then adds.
    assert (await client.delete(f"/resumes/{ids[0]}")).status_code == 204
    assert (await add_resume(client)).status_code == 202


async def test_in3_users_over_the_limit_keep_their_resumes(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_fixtures: Path,
) -> None:
    _, expected = fixture("resumes", "product-manager-mid")
    set_extractor_output(fake_fixtures, "Resume", expected)
    first = (await add_resume(client)).json()["resume"]["id"]
    async with sessionmaker() as db:
        row = await db.scalar(select(ResumeRow))
        assert row is not None
        db.add_all(
            ResumeRow(org_id=row.org_id, user_id=row.user_id, name=f"old {i}") for i in range(6)
        )
        await db.commit()

    listed = (await client.get("/resumes")).json()
    assert len(listed) == 7
    assert (await add_resume(client)).status_code == 422
    assert (await client.delete(f"/resumes/{first}")).status_code == 204
    assert len((await client.get("/resumes")).json()) == 6
    assert (await add_resume(client)).status_code == 422


# --- job descriptions (IN-1, IN-2) ----------------------------------------------------------


async def test_in1_posting_over_2500_words_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/job-targets", json={"text": words(limits.MAX_POSTING_WORDS + 1)})
    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "code": "posting_too_long",
        "message": (
            "Job descriptions can be up to 2,500 words. Trim the benefits and company boilerplate."
        ),
    }
    with_url = await client.post(
        "/job-targets",
        json={"text": words(limits.MAX_POSTING_WORDS + 1), "url": "https://jobs.lever.co/x/1"},
    )
    assert with_url.json()["detail"]["code"] == "posting_too_long"


async def test_in1_posting_of_2500_words_is_accepted(client: httpx.AsyncClient) -> None:
    resp = await client.post("/job-targets", json={"text": words(limits.MAX_POSTING_WORDS)})
    assert resp.status_code == 202, resp.text


async def test_in1_posting_over_the_character_backstop_is_422(client: httpx.AsyncClient) -> None:
    text = "x" * (limits.MAX_POSTING_CHARS + 1)
    resp = await client.post("/job-targets", json={"text": text})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["type"] == "string_too_long"


async def test_in1_fetched_posting_over_2500_words_asks_for_trimmed_paste(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    ctx[CTX_KEY].fetcher = make_fetcher(
        {
            "api.lever.co/v0/postings/acme/long": httpx.Response(
                200,
                json={"text": "Engineer", "descriptionPlain": words(limits.MAX_POSTING_WORDS + 10)},
            )
        }
    )
    resp = await client.post("/job-targets", json={"url": "https://jobs.lever.co/acme/long"})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job"]["result"] == {
        "outcome": "needs_paste",
        "reason": "too_long",
        "detail": limits.POSTING_TOO_LONG_MESSAGE,
    }
    assert body["job_target"]["status"] == "pending"
    got = await client.get(f"/job-targets/{body['job_target']['id']}")
    assert got.json()["posting"] is None


async def test_in2_match_rejects_text_over_the_character_backstop(
    client: httpx.AsyncClient,
) -> None:
    text = "x" * (limits.MAX_POSTING_CHARS + 1)
    resp = await client.post("/job-targets/match", json={"text": text})
    assert resp.status_code == 422
