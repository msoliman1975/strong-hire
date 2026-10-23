"""CU-5 on the server: candidate text is checked wherever it enters, not only in the web app.

`POST /custom/questions/check` is the web app's pre-check. The same check also runs where text
is stored, so a direct API caller cannot skip it:

- `POST /questions/mine` and `PATCH /questions/mine/{id}` (when the text or the category
  changes) run the full check (clean_text, code_check, the extractor model call) and store the
  cleaned text.
- `POST /sessions` for a Custom session (`check_custom_spec`):
  * every focus chip gets clean_text and code_check, no model call. Chips only go to the
    planner, which quotes them as data;
  * an own question is trusted without a model call when its text (cleaned, case folded) is one
    of the user's saved questions (they were checked when saved), or when this API process
    accepted the same text for the same user within the last hour (`AcceptedTexts`, filled by
    the check endpoint and by saved-question checks). Trusted questions still get code_check;
  * every other own question gets the full check, concurrently.
  A refusal answers 422 and nothing is stored. The stored setup has the cleaned texts.

Rate limit: the check endpoint and the saved-question checks count against the per-minute and
per-day budget (CustomSettings). Checks made while creating a session count against the daily
budget only, so a candidate who just checked their questions in the web app is never refused at
create because of the per-minute budget. Correctness rule: unchecked text never reaches a
session.

Error details:
- 422 `question_refused`: {"code", "message", "refusal", "reason"}; at session create also
  "index" (in `custom.questions`, or in the category's `focus` list), "kind" ("question" or
  "focus") and "category";
- 429 `rate_limited`: {"code", "message", "retry_after_s"} with a Retry-After header;
- 503 `check_unavailable`: {"code", "message"} when the model call failed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Final

from fastapi import HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.custom.check import CheckResult, Kind, check_question, clean_text, code_check
from strong_api.custom.limits import CustomSettings, SlidingWindowLimiter
from strong_core.db.models import SavedQuestion
from strong_core.gateway import ModelGateway
from strong_core.schemas import CustomSessionSpec, InterviewType

log = logging.getLogger(__name__)

RATE_LIMITED = "rate_limited"
CHECK_UNAVAILABLE = "check_unavailable"
QUESTION_REFUSED = "question_refused"

ACCEPTED_TTL_S: Final = 3600.0


def trust_key(text: str) -> str:
    """Texts with the same key are the same question for trust: cleaned and case folded only
    (punctuation is kept, so a trusted text cannot gain characters)."""
    return clean_text(text).casefold()


class AcceptedTexts:
    """Texts the CU-5 model check accepted, per user, for `ttl_s` seconds. In process only."""

    def __init__(self, ttl_s: float = ACCEPTED_TTL_S) -> None:
        self.ttl_s = ttl_s
        self._seen: dict[tuple[uuid.UUID, Kind, str], float] = {}

    def remember(self, user_id: uuid.UUID, kind: Kind, text: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if len(self._seen) > 10_000:  # drop expired entries now and then
            self._seen = {k: t for k, t in self._seen.items() if t > now - self.ttl_s}
        self._seen[(user_id, kind, trust_key(text))] = now

    def knows(self, user_id: uuid.UUID, kind: Kind, text: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        seen = self._seen.get((user_id, kind, trust_key(text)))
        return seen is not None and seen > now - self.ttl_s


def limiter(request: Request) -> SlidingWindowLimiter:
    found: SlidingWindowLimiter | None = getattr(request.app.state, "custom_check_limiter", None)
    if found is None:
        found = SlidingWindowLimiter()
        request.app.state.custom_check_limiter = found
    return found


def accepted_texts(request: Request) -> AcceptedTexts:
    found: AcceptedTexts | None = getattr(request.app.state, "custom_accepted_texts", None)
    if found is None:
        found = AcceptedTexts()
        request.app.state.custom_accepted_texts = found
    return found


def count_check(
    request: Request, user_id: uuid.UUID, settings: CustomSettings, *, daily_only: bool = False
) -> None:
    """Count one model-backed check. Raise 429 `rate_limited` over the budget."""
    per_day = settings.custom_check_per_day
    per_minute = per_day if daily_only else settings.custom_check_per_minute
    wait = limiter(request).hit(user_id, per_minute, per_day)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {
                "code": RATE_LIMITED,
                "message": "You checked many questions. Wait a moment, then try again.",
                "retry_after_s": wait,
            },
            headers={"Retry-After": str(wait)},
        )


def _unavailable(exc: BaseException) -> HTTPException:
    log.warning("custom question check failed: %s", type(exc).__name__)
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        {
            "code": CHECK_UNAVAILABLE,
            "message": "We could not check this right now. Please try again.",
        },
    )


async def run_check(
    gateway: ModelGateway, text: str, kind: Kind, category: InterviewType | None
) -> CheckResult:
    """The CU-5 check; 503 `check_unavailable` when the model call fails."""
    try:
        return await check_question(gateway, text, kind, category)
    except Exception as exc:
        raise _unavailable(exc) from exc


def refused(result: CheckResult, **where: Any) -> HTTPException:
    """422 `question_refused` for a refused check."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {
            "code": QUESTION_REFUSED,
            "message": result.reason,
            "refusal": result.refusal.value if result.refusal else None,
            "reason": result.reason,
            **where,
        },
    )


async def check_saved_question(
    request: Request,
    gateway: ModelGateway,
    user_id: uuid.UUID,
    settings: CustomSettings,
    text: str,
    category: InterviewType,
) -> CheckResult:
    """The full check before a saved question is stored. Raises 422, 429 or 503."""
    count_check(request, user_id, settings)
    result = await run_check(gateway, text, "question", category)
    if not result.accepted:
        log.info("saved question refused: %s", result.refusal)
        raise refused(result)
    accepted_texts(request).remember(user_id, "question", text)
    return result


async def _saved_keys(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> set[str]:
    texts = await db.scalars(
        select(SavedQuestion.text).where(
            SavedQuestion.org_id == org_id, SavedQuestion.user_id == user_id
        )
    )
    return {trust_key(t) for t in texts}


async def check_custom_spec(
    request: Request,
    db: AsyncSession,
    gateway: ModelGateway,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    settings: CustomSettings,
    spec: CustomSessionSpec,
) -> CustomSessionSpec:
    """CU-5 for a new Custom session. Returns the setup with cleaned texts, or raises 422
    `question_refused`, 429 `rate_limited` or 503 `check_unavailable`."""
    data = spec.model_dump(mode="json")
    for category in data["categories"]:
        chips: list[str] = []
        for i, chip in enumerate(category["focus"]):
            clean = clean_text(chip)
            result = code_check(clean, "focus")
            if result is not None:
                log.info("focus chip refused at session create: %s", result.refusal)
                raise refused(result, index=i, kind="focus", category=category["category"])
            chips.append(clean)
        category["focus"] = chips

    saved = await _saved_keys(db, org_id, user_id) if data["questions"] else set()
    cache = accepted_texts(request)
    pending: list[tuple[int, str, InterviewType]] = []
    for i, question in enumerate(data["questions"]):
        clean = clean_text(question["text"])
        result = code_check(clean, "question")
        if result is not None:
            log.info("own question refused at session create: %s", result.refusal)
            raise refused(result, index=i, kind="question", category=question["category"])
        question["text"] = clean
        if trust_key(clean) in saved or cache.knows(user_id, "question", clean):
            continue
        pending.append((i, clean, InterviewType(question["category"])))

    for _ in pending:
        count_check(request, user_id, settings, daily_only=True)
    results = await asyncio.gather(
        *(check_question(gateway, text, "question", cat) for _, text, cat in pending),
        return_exceptions=True,
    )
    for result_or_error in results:
        if isinstance(result_or_error, BaseException):
            raise _unavailable(result_or_error) from result_or_error
    for (i, text, cat), checked in zip(pending, results, strict=True):
        assert isinstance(checked, CheckResult)
        if not checked.accepted:
            log.info("own question refused at session create: %s", checked.refusal)
            raise refused(checked, index=i, kind="question", category=cat.value)
        cache.remember(user_id, "question", text)

    try:
        return CustomSessionSpec.model_validate(data)
    except ValidationError as exc:  # cleaning made two questions the same
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ) from exc
