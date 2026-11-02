"""RF-11: the one-off, rule-based move of stored job targets into the wave 1 families."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import AuditLog, JobTarget
from strong_core.schemas import RoleFamily
from strong_worker.inputs.reclassify import ACTION, proposed_family, reclassify_job_targets

F = RoleFamily


@pytest.mark.parametrize(
    ("title", "current", "expected"),
    [
        ("Site Reliability Engineer", F.SWE, F.INFRA_SECURITY),
        ("Senior DevOps Engineer", F.SWE, F.INFRA_SECURITY),
        ("Security Engineer", F.SWE, F.INFRA_SECURITY),
        ("Software Engineer, Platform", F.SWE, None),  # tie: stays swe
        ("Senior Software Engineer", F.SWE, None),
        ("Senior Data Analyst", F.DATA_ML, F.DATA_ANALYTICS),
        ("Data Scientist, Product Analytics", F.DATA_ML, None),  # data scientist is more specific
        ("Machine Learning Engineer", F.DATA_ML, None),
        ("Engineering Manager, Payments", F.SWE, F.ENG_MANAGEMENT),
        ("Director of Engineering", F.OTHER, F.ENG_MANAGEMENT),
        ("Program Manager, Operations", F.TPM, F.PROJECT_PROGRAM),
        ("Technical Program Manager", F.TPM, None),
        ("Financial Analyst", F.OTHER, F.FINANCE),
        ("FP&A Manager", F.OTHER, F.FINANCE),
        ("Strategy Consultant", F.OTHER, F.CONSULTING_STRATEGY),
        ("Chief of Staff to the CEO", F.OTHER, F.CONSULTING_STRATEGY),
        ("Nurse Practitioner", F.OTHER, None),
        ("Product Manager", F.PM, None),  # not a family wave 1 split
        ("Financial Analyst", F.FINANCE, None),  # already moved
        ("", F.OTHER, None),
    ],
)
def test_rf11_title_rule(title: str, current: RoleFamily, expected: RoleFamily | None) -> None:
    """RF-11: a title moves only into a clearly more specific wave 1 family."""
    assert proposed_family(title, current) == expected


async def _target(
    maker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID], **posting: Any
) -> uuid.UUID:
    org_id, user_id = account
    parsed = {
        "company_name": "Unknown",
        "must_have_skills": [],
        "nice_to_have_skills": [],
        "responsibilities": [],
        **posting,
    }
    async with maker() as db:
        row = JobTarget(org_id=org_id, user_id=user_id, raw_text="posting", parsed_json=parsed)
        db.add(row)
        await db.commit()
        return row.id


async def _family(maker: async_sessionmaker[AsyncSession], rid: uuid.UUID) -> str:
    async with maker() as db:
        row = await db.get(JobTarget, rid)
        assert row is not None and row.parsed_json is not None
        return str(row.parsed_json["role_family"])


async def test_rf11_dry_run_writes_nothing_then_apply_moves_and_audits(
    sessionmaker: async_sessionmaker[AsyncSession], account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """RF-11: dry run by default, every change printed and audited, no model calls."""
    analyst = await _target(sessionmaker, account, title="Financial Analyst", role_family="other")
    sre = await _target(sessionmaker, account, title="Site Reliability Engineer", role_family="swe")
    swe = await _target(sessionmaker, account, title="Backend Engineer", role_family="swe")
    async with sessionmaker() as db:  # a target still being read
        db.add(JobTarget(org_id=account[0], user_id=account[1], raw_text="x", parsed_json=None))
        await db.commit()

    dry = await reclassify_job_targets(sessionmaker)
    assert dry.outcomes == {"would_move": 2, "unchanged": 1}
    assert dry.moves == {"other -> finance": 1, "swe -> infra_security": 1}
    assert await _family(sessionmaker, analyst) == "other"

    done = await reclassify_job_targets(sessionmaker, apply=True)
    assert done.outcomes == {"moved": 2, "unchanged": 1}
    assert await _family(sessionmaker, analyst) == "finance"
    assert await _family(sessionmaker, sre) == "infra_security"
    assert await _family(sessionmaker, swe) == "swe"
    async with sessionmaker() as db:
        audits = (await db.scalars(select(AuditLog).where(AuditLog.action == ACTION))).all()
    assert sorted(a.entity for a in audits) == sorted(
        [f"job_target:{analyst}", f"job_target:{sre}"]
    )

    again = await reclassify_job_targets(sessionmaker, apply=True)
    assert again.outcomes == {"unchanged": 3}  # idempotent
