"""Custom interview endpoints (docs/custom-interview-spec.md).

    POST   /custom/questions/check     CU-5: check and tag one own question or focus chip
    GET    /custom/focus               CU-2: suggested focus chips per category
    GET    /questions/mine             CU-8: the user's saved questions, newest first
    POST   /questions/mine             CU-8: save one (409 at the cap or for a duplicate)
    PATCH  /questions/mine/{id}        CU-8: edit text, category or competencies
    DELETE /questions/mine/{id}        CU-8: delete one

The check calls the model once (role extractor), so it is rate limited per user and locked like
Custom sessions under `custom_interview_access=paid_only` (CU-11, strong_api.custom.access).
Saved questions and focus chips are never locked. Saving or editing a question (text or
category) runs the same check on the server (strong_api.custom.guard), counted in the same
rate limit; the cleaned text is stored.

Error details are {"code", "message", ...}:
- 403 `upgrade_required` (CU-11), 429 `rate_limited` (with `retry_after_s`),
  503 `check_unavailable` when the model call failed;
- 409 `saved_questions_full` and `duplicate_question` for saved questions;
- 422 `question_refused` (with `refusal` and `reason`) when a saved question fails the check.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from strong_api.custom.access import ensure_custom_allowed
from strong_api.custom.check import clean_text, find_duplicate, normalize_for_duplicates
from strong_api.custom.focus import suggest_focus
from strong_api.custom.guard import accepted_texts, check_saved_question, count_check, run_check
from strong_api.custom.limits import CustomSettings, get_custom_settings
from strong_api.custom.schemas import (
    CategoryFocus,
    FocusSuggestions,
    QuestionCheckOut,
    QuestionCheckRequest,
    SavedQuestionIn,
    SavedQuestionOut,
    SavedQuestionPatch,
)
from strong_api.inputs.deps import Db, Me
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import JobTarget, SavedQuestion
from strong_core.gateway import get_gateway
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    Competency,
    CustomQuestion,
    GapAnalysis,
    GapStatus,
    InterviewType,
    JobPosting,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["custom interview"])

Settings = Annotated[CustomSettings, Depends(get_custom_settings)]

SAVED_QUESTIONS_FULL = "saved_questions_full"
DUPLICATE_QUESTION = "duplicate_question"

_CHECK_RESPONSES: dict[int | str, dict[str, object]] = {
    403: {"description": "CU-11: Custom is locked. detail.code is 'upgrade_required'."},
    429: {"description": "Rate limited. detail.code is 'rate_limited'; see Retry-After."},
    503: {"description": "The check could not run. detail.code is 'check_unavailable'."},
}
_SAVED_RESPONSES: dict[int | str, dict[str, object]] = {
    409: {"description": "detail.code is 'saved_questions_full' or 'duplicate_question'."},
    422: {
        "description": "CU-5: detail.code is 'question_refused' (with refusal and reason) when "
        "the check refuses the text; else a bad field."
    },
    429: {"description": "Rate limited. detail.code is 'rate_limited'; see Retry-After."},
    503: {"description": "The check could not run. detail.code is 'check_unavailable'."},
}


# --- CU-5 ------------------------------------------------------------------------------------


@router.post("/custom/questions/check", responses=_CHECK_RESPONSES)
async def check_custom_question(
    body: QuestionCheckRequest, request: Request, db: Db, me: Me, settings: Settings
) -> QuestionCheckOut:
    """CU-5: refuse text that is not an interview question (or topic), abuse, or instructions to
    the interviewer; else tag it with a category and 1 to 3 competencies. Flags a near-duplicate
    of an entry of `existing`. Rate limited per user."""
    await ensure_custom_allowed(db, me)
    count_check(request, me.user_id, settings)
    result = await run_check(get_gateway(), body.text, body.kind, body.category)
    if result.accepted:
        # A session created soon with this text needs no second model call (guard.py).
        accepted_texts(request).remember(me.user_id, body.kind, clean_text(body.text))
    else:
        log.info("custom %s refused: %s", body.kind, result.refusal)
    return QuestionCheckOut(
        accepted=result.accepted,
        refusal=result.refusal,
        reason=result.reason,
        category=result.category,
        competencies=list(result.competencies),
        duplicate_of=find_duplicate(body.text, body.existing),
    )


# --- CU-2 ------------------------------------------------------------------------------------


@router.get("/custom/focus")
async def focus_suggestions(
    db: Db,
    me: Me,
    job_id: Annotated[uuid.UUID, Query(description="The job target.")],
    resume_id: Annotated[
        uuid.UUID | None,
        Query(description="The CV. Default: the CV of the job's latest ready gap analysis."),
    ] = None,
) -> FocusSuggestions:
    """CU-2: focus chips per category from the latest ready gap analysis for the job and CV
    (session plan topics, probe areas, gaps, weak competencies) and the job's must-have
    skills. The first chips of each category are pre-selected."""
    target = await db.scalar(
        select(JobTarget).where(
            JobTarget.id == job_id,
            JobTarget.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
        )
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
    posting = None
    if target.parsed_json is not None:
        try:
            posting = JobPosting.model_validate(target.parsed_json)
        except ValidationError:
            posting = None
    query = select(GapRow).where(
        GapRow.job_target_id == target.id,
        GapRow.org_id == me.org_id,
        GapRow.status == GapStatus.READY,
        GapRow.breakdown_json.is_not(None),
    )
    if resume_id is not None:
        query = query.where(GapRow.resume_id == resume_id)
    row = await db.scalar(query.order_by(GapRow.created_at.desc(), GapRow.id.desc()).limit(1))
    gap = None
    if row is not None and row.breakdown_json is not None:
        try:
            gap = GapAnalysis.model_validate(row.breakdown_json)
        except ValidationError:
            gap = None
    chips = suggest_focus(posting, gap)

    def focus(itype: InterviewType) -> CategoryFocus:
        suggested, preselected = chips[itype]
        return CategoryFocus(suggested=suggested, preselected=preselected)

    return FocusSuggestions(
        job_target_id=target.id,
        gap_analysis_id=row.id if gap is not None and row is not None else None,
        behavioral=focus(InterviewType.BEHAVIORAL),
        technical_qa=focus(InterviewType.TECHNICAL_QA),
        hiring_manager=focus(InterviewType.HIRING_MANAGER),
        case=focus(InterviewType.CASE),
    )


# --- CU-8 ------------------------------------------------------------------------------------


def _saved_out(row: SavedQuestion) -> SavedQuestionOut:
    return SavedQuestionOut(
        id=row.id,
        text=row.text,
        category=row.category,
        competencies=row.competencies,
        bank_ref=row.bank_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validated(text: str, category: InterviewType, competencies: list[str]) -> CustomQuestion:
    """The same limits as an own question in a session (CU-3). 422 when they fail."""
    try:
        return CustomQuestion.model_validate(
            {"text": text, "category": category, "competencies": competencies}
        )
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ) from exc


def _competencies(
    category: InterviewType, given: list[Competency], checked: tuple[Competency, ...]
) -> list[str]:
    """The given competencies when there are some and all belong to the category, else the
    ones the CU-5 check tagged."""
    allowed = COMPETENCIES_BY_TYPE[category]
    if given and all(c in allowed for c in given):
        return [c.value for c in given]
    return [c.value for c in checked]


async def _mine(db: Db, me: Me) -> list[SavedQuestion]:
    rows = await db.scalars(
        select(SavedQuestion)
        .where(SavedQuestion.org_id == me.org_id, SavedQuestion.user_id == me.user_id)
        .order_by(SavedQuestion.created_at.desc(), SavedQuestion.id.desc())
    )
    return list(rows)


def _ensure_unique(rows: list[SavedQuestion], text: str, skip: uuid.UUID | None = None) -> None:
    mine = normalize_for_duplicates(text)
    if any(r.id != skip and normalize_for_duplicates(r.text) == mine for r in rows):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": DUPLICATE_QUESTION, "message": "This question is already in your list."},
        )


async def _owned_saved(db: Db, me: Me, question_id: uuid.UUID) -> SavedQuestion:
    row = await db.scalar(
        select(SavedQuestion).where(
            SavedQuestion.id == question_id,
            SavedQuestion.org_id == me.org_id,
            SavedQuestion.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")
    return row


@router.get("/questions/mine")
async def list_saved_questions(db: Db, me: Me) -> list[SavedQuestionOut]:
    """CU-8: the user's saved questions, newest first."""
    return [_saved_out(r) for r in await _mine(db, me)]


@router.post("/questions/mine", status_code=status.HTTP_201_CREATED, responses=_SAVED_RESPONSES)
async def save_question(
    body: SavedQuestionIn, request: Request, db: Db, me: Me, settings: Settings
) -> SavedQuestionOut:
    """CU-8: save a question (typed, from a session, or from the bank with `bank_ref`).

    CU-5: the text is checked on the server first (422 `question_refused`) and stored cleaned.
    Without competencies, or with ones not of the category, the check's tags are stored."""
    text = clean_text(body.text)
    rows = await _mine(db, me)
    if len(rows) >= settings.saved_questions_max:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": SAVED_QUESTIONS_FULL,
                "message": f"You can keep {settings.saved_questions_max} questions. "
                "Delete one to add another.",
            },
        )
    _ensure_unique(rows, text)
    checked = await check_saved_question(
        request, get_gateway(), me.user_id, settings, text, body.category
    )
    competencies = _competencies(body.category, body.competencies, checked.competencies)
    question = _validated(text, body.category, competencies)
    row = SavedQuestion(
        org_id=me.org_id,
        user_id=me.user_id,
        text=question.text,
        category=question.category,
        competencies=[c.value for c in question.competencies],
        bank_ref=body.bank_ref,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _saved_out(row)


@router.patch("/questions/mine/{question_id}", responses=_SAVED_RESPONSES)
async def edit_saved_question(
    question_id: uuid.UUID,
    body: SavedQuestionPatch,
    request: Request,
    db: Db,
    me: Me,
    settings: Settings,
) -> SavedQuestionOut:
    """CU-8: change the text, the category or the competencies.

    CU-5: a new text or category is checked on the server first (422 `question_refused`), and
    the text is stored cleaned. When the competencies (given, or kept) do not fit the category,
    the check's tags are stored. Changing only the competencies needs no check."""
    row = await _owned_saved(db, me, question_id)
    text = clean_text(body.text) if body.text is not None else row.text
    category = body.category if body.category is not None else row.category
    competencies = (
        [c.value for c in body.competencies] if body.competencies is not None else row.competencies
    )
    if text != row.text or category != row.category:
        if text != row.text:
            _ensure_unique(await _mine(db, me), text, skip=row.id)
        checked = await check_saved_question(
            request, get_gateway(), me.user_id, settings, text, category
        )
        competencies = _competencies(
            category, [Competency(c) for c in competencies], checked.competencies
        )
    question = _validated(text, category, competencies)
    row.text = question.text
    row.category = question.category
    row.competencies = [c.value for c in question.competencies]
    await db.commit()
    await db.refresh(row)
    return _saved_out(row)


@router.delete("/questions/mine/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_question(question_id: uuid.UUID, db: Db, me: Me) -> Response:
    """CU-8: delete a saved question. Sessions that used it keep their copy."""
    row = await _owned_saved(db, me, question_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
