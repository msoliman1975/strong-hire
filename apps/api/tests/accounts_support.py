"""Helpers for the billing and account tests (P9): a fake Stripe, signed webhook fixtures,
sign-up through the real auth routes, and rows in every user-owned table."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import (
    AuditLog,
    CompanyRequest,
    ExitSurvey,
    GapAnalysis,
    InterviewerTrace,
    InterviewSession,
    JobTarget,
    ProgressSnapshot,
    Resume,
    Scorecard,
    Subscription,
    Turn,
    UsageEvent,
    User,
)
from strong_core.schemas import (
    Competency,
    Difficulty,
    HireSignal,
    InterviewType,
    Mode,
    Phase,
    SessionStatus,
    Speaker,
    SubscriptionStatus,
    UsageComponent,
)

STRIPE_FIXTURES = Path(__file__).parent / "fixtures" / "stripe"
WEBHOOK_SECRET = "whsec_test_secret_for_p9"
CUSTOMER_ID = "cus_TEST123"
SUBSCRIPTION_ID = "sub_TEST123"


def load_event(name: str, user_id: uuid.UUID | str | None = None, **changes: Any) -> dict[str, Any]:
    """A Stripe event fixture. `changes` replace keys of data.object."""
    text = (STRIPE_FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    if user_id is not None:
        text = text.replace("USER_ID", str(user_id))
    event: dict[str, Any] = json.loads(text)
    event["data"]["object"].update(changes)
    return event


def sign(payload: bytes, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    """The Stripe-Signature header, computed the way Stripe documents it."""
    ts = int(time.time()) if timestamp is None else timestamp
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


async def post_event(
    client: httpx.AsyncClient, event: dict[str, Any], secret: str = WEBHOOK_SECRET
) -> httpx.Response:
    payload = json.dumps(event).encode()
    return await client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret), "Content-Type": "application/json"},
    )


def subscription_object(event_name: str) -> dict[str, Any]:
    obj: dict[str, Any] = load_event(event_name)["data"]["object"]
    return obj


class FakeStripe:
    """Records calls and answers like Stripe test mode, without the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.subscriptions: dict[str, dict[str, Any]] = {
            SUBSCRIPTION_ID: subscription_object("customer_subscription_created")
        }
        self.deleted_customers: list[str] = []

    async def create_customer(self, *, email: str, user_id: str, org_id: str) -> str:
        self.calls.append(("create_customer", {"email": email, "user_id": user_id}))
        return CUSTOMER_ID

    async def create_checkout_session(
        self, *, customer_id: str, user_id: str, success_url: str, cancel_url: str
    ) -> str:
        self.calls.append(
            (
                "checkout",
                {"customer_id": customer_id, "user_id": user_id, "success_url": success_url},
            )
        )
        return "https://checkout.stripe.com/c/pay/cs_test_TEST123"

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, cancel_subscription_id: str | None = None
    ) -> str:
        self.calls.append(
            ("portal", {"customer_id": customer_id, "cancel": cancel_subscription_id})
        )
        return "https://billing.stripe.com/p/session/test_TEST123"

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        self.calls.append(("retrieve_subscription", {"id": subscription_id}))
        return copy.deepcopy(self.subscriptions[subscription_id])

    async def delete_customer(self, customer_id: str) -> None:
        self.deleted_customers.append(customer_id)


async def sign_up(client: httpx.AsyncClient, email: str = "ana@example.com") -> dict[str, Any]:
    """Sign up and sign in through the real auth routes. The client keeps the cookie."""
    assert (await client.post("/auth/dev-login", json={"email": email})).status_code == 200
    resp = await client.post("/auth/signup", json={"age_confirmed": True, "terms_accepted": True})
    assert resp.status_code == 200, resp.text
    user: dict[str, Any] = resp.json()["user"]
    return user


async def add_session(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    started: bool = True,
    status: SessionStatus = SessionStatus.COMPLETED,
    minutes: int = 30,
    duration: int = 45,
) -> InterviewSession:
    job = JobTarget(org_id=org_id, user_id=user_id, raw_text="Engineer")
    db.add(job)
    await db.flush()
    now = datetime.now(UTC)
    start = now - timedelta(minutes=minutes) if started else None
    session = InterviewSession(
        org_id=org_id,
        job_target_id=job.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=duration,
        status=status,
        started_at=start,
        ended_at=now if started else None,
    )
    db.add(session)
    await db.commit()
    return session


async def fill_every_user_table(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, file_ref: str | None
) -> set[str]:
    """One or more rows in each user-owned table for the org. Returns the table names filled."""
    resume = Resume(
        org_id=org_id, user_id=user_id, parsed_json={"summary": "Engineer"}, file_ref=file_ref
    )
    job = JobTarget(org_id=org_id, user_id=user_id, raw_text="Senior engineer at Stripe")
    db.add_all([resume, job])
    await db.flush()
    gap = GapAnalysis(
        org_id=org_id,
        job_target_id=job.id,
        resume_id=resume.id,
        match_score=72,
        breakdown_json={"match_score": 72},
        session_plan_json=[],
        model_version="planner:test",
    )
    session = InterviewSession(
        org_id=org_id,
        job_target_id=job.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=30,
        status=SessionStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        ended_at=datetime.now(UTC),
        minutes_billed=30,
    )
    db.add_all([gap, session])
    await db.flush()
    db.add_all(
        [
            Turn(
                org_id=org_id,
                session_id=session.id,
                speaker=Speaker.CANDIDATE,
                phase=Phase.CORE,
                text="I led the payments migration.",
                start_ms=0,
                end_ms=4000,
            ),
            Scorecard(
                org_id=org_id,
                session_id=session.id,
                hire_signal=HireSignal.LEAN_HIRE,
                rationale="Clear ownership.",
                competency_scores_json=[],
                value_scores_json=[],
                per_question_json=[],
                scorer_model="scorer:test",
                rubric_version="scorer/scorecard.v1",
            ),
            ProgressSnapshot(
                org_id=org_id,
                job_target_id=job.id,
                competency=Competency.OWNERSHIP,
                score=Decimal("3.00"),
                session_id=session.id,
                at=datetime.now(UTC),
            ),
            UsageEvent(
                org_id=org_id,
                session_id=session.id,
                component=UsageComponent.LLM,
                units=Decimal("1200"),
                cost_usd=Decimal("0.012"),
            ),
            CompanyRequest(
                org_id=org_id,
                user_id=user_id,
                job_target_id=job.id,
                company_name="Stripe",
                normalized_name="stripe",
            ),
            Subscription(
                org_id=org_id,
                user_id=user_id,
                status=SubscriptionStatus.ACTIVE,
                minutes_cap=300,
                minutes_used=30,
            ),
            ExitSurvey(org_id=org_id, user_id=user_id, reason="got_the_job", got_job="yes"),
            InterviewerTrace(
                org_id=org_id,
                session_id=session.id,
                seq=1,
                turn_index=0,
                call="say",
                move="greet",
                reason_json={"why": ["start"]},
                phase=Phase.INTRO,
                elapsed_ms=0,
                phase_deadline_ms=60_000,
                messages_json=[{"role": "user", "content": "Greet the candidate."}],
                raw_reply="Hi, I am Alex.",
                spoken_text="Hi, I am Alex.",
                input_tokens=100,
                output_tokens=10,
            ),
            AuditLog(org_id=org_id, actor="test", action="test.row", entity="test"),
        ]
    )
    await db.commit()
    return {
        "users",
        "subscriptions",
        "resumes",
        "job_targets",
        "gap_analyses",
        "sessions",
        "turns",
        "scorecards",
        "progress_snapshots",
        "usage_events",
        "company_requests",
        "exit_surveys",
        "interviewer_traces",
    }


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, uuid.UUID(user_id))
