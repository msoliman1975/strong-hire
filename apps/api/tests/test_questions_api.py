"""The Questions page API: GET /questions and GET /questions/companies (QB-1 to QB-3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db.models import Company
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.schemas import ProfileStatus

EXAMPLE = get_settings().repo_root / "profiles/examples/example-corp.json"


def _hints(word: str) -> dict[str, list[str]]:
    return {
        "looking_for": [f"How you handle {word}"],
        "strong_signals": ["A measured result"],
        "watch_outs": ["A team story with no 'I'"],
    }


SAMPLES: list[dict[str, Any]] = [
    {
        "interview_type": "behavioral",
        "question": "Tell me about a time you owned a customer problem end to end.",
        "strong_answer": "Own actions and a measured result.",
        "competencies": ["ownership"],
        "values": ["Own the outcome"],
        "source_url": "https://example.com/a",
        "hints": _hints("ownership"),
    },
    {
        "interview_type": "technical_qa",
        "question": "How would you design a rate limiter?",
        "strong_answer": "Clarify limits, compare algorithms, discuss trade-offs.",
        "competencies": ["trade_offs"],
        "source_url": "https://example.com/b",
        "hints": _hints("trade-offs"),
        "role_families": ["swe"],
        "levels": ["senior", "staff_principal"],
    },
    {
        "interview_type": "behavioral",
        "question": "Why do you want to join us?",
        "strong_answer": "Specific reasons tied to the mission.",
        "source_url": "https://example.com/c",
    },
]

GENERAL: dict[str, Any] = {
    "version": 1,
    "questions": [
        {
            "id": "disagree-with-manager",
            "interview_type": "behavioral",
            "question": "Tell me about a time you disagreed with your manager.",
            "hints": _hints("disagreement"),
            "competencies": ["conflict_handling"],
        },
        {
            "id": "size-a-market",
            "interview_type": "case",
            "question": "How many ride-share trips happen in a city each day?",
            "hints": _hints("estimation"),
            "competencies": ["estimation_logic"],
            "role_families": ["pm", "data_ml"],
        },
    ],
}


@pytest.fixture(autouse=True)
def _general_bank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "questions"
    folder.mkdir()
    (folder / "general.json").write_text(json.dumps(GENERAL), encoding="utf-8")
    monkeypatch.setenv("QUESTIONS_DIR", str(folder))
    get_settings.cache_clear()


async def _publish(
    maker: async_sessionmaker[AsyncSession], slug: str, status: ProfileStatus
) -> None:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["sample_questions"] = SAMPLES
    async with maker() as db:
        company = await db.scalar(select(Company).where(Company.slug == slug))
        assert company is not None
        db.add(
            ProfileRow(
                company_id=company.id,
                version=1,
                status=status,
                profile_json=data,
                sources_json=data["sources"],
            )
        )
        await db.commit()


@pytest.fixture
async def bank(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    await _publish(sessionmaker, "stripe", ProfileStatus.PUBLISHED)
    await _publish(sessionmaker, "google", ProfileStatus.DRAFT)


def _questions(body: dict[str, Any], key: str) -> list[str]:
    return [q["question"] for q in body[key]]


async def test_qb1_companies_lists_published_profiles_only(
    client: httpx.AsyncClient, bank: None
) -> None:
    """QB-1: the company filter offers companies with a Published profile."""
    resp = await client.get("/questions/companies")
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"slug": "stripe", "name": "Stripe", "question_count": 3}]


async def test_qb1_qb2_unfiltered_lists_company_and_general_questions(
    client: httpx.AsyncClient, bank: None
) -> None:
    """QB-1, QB-2: every question with its tags and hints."""
    body = (await client.get("/questions")).json()
    assert body["company"] is None
    assert len(body["company_questions"]) == 3 and len(body["general_questions"]) == 2
    first = body["company_questions"][0]
    assert first["id"] == "stripe-1" and first["source"] == "company"
    assert first["company_name"] == "Stripe" and first["values"] == ["Own the outcome"]
    assert first["hints"]["looking_for"] == ["How you handle ownership"]
    assert first["source_url"] == "https://example.com/a"
    assert body["company_questions"][2]["hints"] is None  # hints not written yet
    general = body["general_questions"][0]
    assert general["id"] == "disagree-with-manager" and general["source"] == "general"
    assert general["company_slug"] is None and general["source_url"] is None


async def test_qb3_company_first_then_general(client: httpx.AsyncClient, bank: None) -> None:
    """QB-3: a selected company's questions, then general ones matching the other filters."""
    body = (await client.get("/questions", params={"company": "stripe"})).json()
    assert body["company"]["name"] == "Stripe"
    assert len(body["company_questions"]) == 3 and len(body["general_questions"]) == 2

    general = (await client.get("/questions", params={"company": "general"})).json()
    assert general["company"] is None and general["company_questions"] == []
    assert len(general["general_questions"]) == 2

    for slug in ("google", "nope"):  # a Draft profile is not in the bank
        assert (await client.get("/questions", params={"company": slug})).status_code == 404


async def test_qb1_filters(client: httpx.AsyncClient, bank: None) -> None:
    """QB-1: type, area, job category, level and text search. Empty tags fit everything."""

    async def get(**params: Any) -> dict[str, Any]:
        resp = await client.get("/questions", params=params)
        assert resp.status_code == 200, resp.text
        body: dict[str, Any] = resp.json()
        return body

    body = await get(interview_type="behavioral")
    assert len(body["company_questions"]) == 2
    assert _questions(body, "general_questions") == [
        "Tell me about a time you disagreed with your manager."
    ]

    body = await get(competency=["trade_offs", "estimation_logic"])
    assert _questions(body, "company_questions") == ["How would you design a rate limiter?"]
    assert len(body["general_questions"]) == 1

    body = await get(role_family="pm")
    assert len(body["company_questions"]) == 2  # the swe-only question is left out
    assert len(body["general_questions"]) == 2

    body = await get(level="new_grad")
    assert "How would you design a rate limiter?" not in _questions(body, "company_questions")

    body = await get(q="DISAGREEMENT")  # matches the hints too, ignoring case
    assert body["company_questions"] == []
    assert len(body["general_questions"]) == 1

    assert (await client.get("/questions", params={"level": "intern"})).status_code == 422
    # Custom is a session type, not a question category (CU-1)
    assert (await client.get("/questions", params={"interview_type": "custom"})).status_code == 422


async def test_rs1_recruiter_screen_filter_lists_no_bank_questions(
    client: httpx.AsyncClient, bank: None
) -> None:
    """RS-1: recruiter_screen is a valid type filter. The bank holds no recruiter screen
    questions yet (general.json and the profiles have the four standard types only)."""
    resp = await client.get("/questions", params={"interview_type": "recruiter_screen"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company_questions"] == [] and body["general_questions"] == []


async def test_qb1_needs_sign_in(anon_client: httpx.AsyncClient) -> None:
    """QB-1: signed-in users only."""
    assert (await anon_client.get("/questions")).status_code == 401
    assert (await anon_client.get("/questions/companies")).status_code == 401
