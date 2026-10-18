"""Competency trends (PR-1) and the recommended next session (PR-2). Rules in code, no model.

Next session. Each interview type gets points:
- weakness: for each competency of that type with a latest score under 3, 3 minus the score;
- remaining gap: if the gap analysis plan lists the type and no session of that type is done
  yet, 1 point for plan priority 1, 0.75 for priority 2, 0.5 for 3, and 0.25 after that.
The type with the most points wins (ties go to the better plan priority). When nothing scores
points but there are scores, every competency meets the bar: the advice is a Tough session on
the type with the lowest average. With no scores and no plan, there is no advice. The advice is
always one of the four standard types.

Custom sessions (CU-7): their Realistic snapshots count like any other. `split_question_scores`
tells which scores came from the candidate's own questions, so the progress can mark those
points, or recompute them without own questions (`without_own_questions`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from strong_api.scoring.schemas import CompetencyTrend, OwnQuestionPoint
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    Competency,
    Difficulty,
    InterviewType,
    PlannedSession,
    ProgressSnapshot,
    QuestionScore,
    QuestionSource,
)

BAR = 3.0
FLAT_WITHIN = 0.25
PLAN_POINTS = {1: 1.0, 2: 0.75, 3: 0.5}
MAX_TOPICS = 4

TYPE_NAMES = {
    InterviewType.BEHAVIORAL: "behavioral",
    InterviewType.HIRING_MANAGER: "hiring manager",
    InterviewType.TECHNICAL_QA: "technical Q&A",
    InterviewType.CASE: "case",
    InterviewType.CUSTOM: "custom",
}


def label(competency: Competency) -> str:
    return competency.value.replace("_", " ")


def competency_trends(snapshots: Sequence[ProgressSnapshot]) -> list[CompetencyTrend]:
    by: dict[Competency, list[ProgressSnapshot]] = defaultdict(list)
    for s in sorted(snapshots, key=lambda s: s.at):
        by[s.competency].append(s)
    out = []
    for competency, points in by.items():
        first, latest = points[0].score, points[-1].score
        change = round(latest - first, 2)
        if len(points) == 1:
            direction = "single"
        elif abs(change) < FLAT_WITHIN:
            direction = "flat"
        else:
            direction = "up" if change > 0 else "down"
        out.append(
            CompetencyTrend(
                competency=competency,
                sessions=len(points),
                first=first,
                latest=latest,
                change=change,
                average=round(sum(p.score for p in points) / len(points), 2),
                direction=direction,
            )
        )
    return sorted(out, key=lambda t: (t.latest, t.competency.value))


@dataclass
class QuestionSplit:
    """CU-7: a competency's per-question scores in one session, by who wrote the question."""

    own: list[float]
    other: list[float]


def split_question_scores(
    sources: Mapping[str, QuestionSource], per_question: Iterable[QuestionScore]
) -> dict[Competency, QuestionSplit]:
    """Per competency, the scores from the candidate's own questions and from the others.
    A question missing from `sources` counts as the interviewer's."""
    out: dict[Competency, QuestionSplit] = {}
    for q in per_question:
        own = sources.get(q.question_ref) == QuestionSource.CANDIDATE
        for s in q.scores:
            split = out.setdefault(s.competency, QuestionSplit([], []))
            (split.own if own else split.other).append(float(s.score))
    return out


def own_question_points(
    snapshots: Iterable[ProgressSnapshot],
    splits: Mapping[UUID, Mapping[Competency, QuestionSplit]],
) -> list[OwnQuestionPoint]:
    """CU-7: the snapshots that use scores of own questions."""
    out = []
    for s in snapshots:
        split = splits.get(s.session_id, {}).get(s.competency)
        if split is not None and split.own:
            out.append(
                OwnQuestionPoint(
                    session_id=s.session_id,
                    competency=s.competency,
                    own_questions=len(split.own),
                    other_questions=len(split.other),
                )
            )
    return out


def without_own_questions(
    snapshots: Iterable[ProgressSnapshot],
    splits: Mapping[UUID, Mapping[Competency, QuestionSplit]],
) -> list[ProgressSnapshot]:
    """CU-7: snapshots recomputed without the scores of own questions. A point that comes only
    from own questions is left out; a mixed one becomes the average of the other questions."""
    out = []
    for s in snapshots:
        split = splits.get(s.session_id, {}).get(s.competency)
        if split is None or not split.own:
            out.append(s)
        elif split.other:
            score = round(sum(split.other) / len(split.other), 2)
            out.append(s.model_copy(update={"score": score}))
    return out


def latest_scores(snapshots: Iterable[ProgressSnapshot]) -> dict[Competency, float]:
    out: dict[Competency, float] = {}
    for s in sorted(snapshots, key=lambda s: s.at):
        out[s.competency] = s.score
    return out


@dataclass
class _Option:
    interview_type: InterviewType
    points: float = 0.0
    weak: list[tuple[Competency, float]] | None = None
    planned: PlannedSession | None = None


def recommend_next_session(
    scores: Mapping[Competency, float],
    plan: Sequence[PlannedSession],
    practiced: Iterable[InterviewType],
) -> PlannedSession | None:
    """PR-2: the next session from the weakest competencies and the remaining planned gaps."""
    done = set(practiced)
    first_plan: dict[InterviewType, PlannedSession] = {}
    for p in sorted(plan, key=lambda p: p.priority):
        first_plan.setdefault(p.interview_type, p)

    options: list[_Option] = []
    for itype, comps in COMPETENCIES_BY_TYPE.items():
        weak = sorted(
            ((c, scores[c]) for c in comps if c in scores and scores[c] < BAR),
            key=lambda x: (x[1], x[0].value),
        )
        option = _Option(itype, sum(BAR - s for _, s in weak), weak)
        planned = first_plan.get(itype)
        if planned is not None:
            option.planned = planned
            if itype not in done:
                option.points += PLAN_POINTS.get(planned.priority, 0.25)
        options.append(option)

    def plan_rank(o: _Option) -> int:
        return o.planned.priority if o.planned else 99

    best = max(options, key=lambda o: (o.points, -plan_rank(o)))
    if best.points > 0:
        return _advice(best, done)
    if scores:
        return _raise_the_bar(scores)
    return None


def _advice(option: _Option, done: set[InterviewType]) -> PlannedSession:
    weak = option.weak or []
    topics = [label(c).capitalize() for c, _ in weak[:3]]
    if option.planned is not None:
        topics += [t for t in option.planned.focus_topics if t not in topics]
    if not topics:
        topics = [f"{TYPE_NAMES[option.interview_type].capitalize()} practice"]
    reasons = []
    if weak:
        listed = ", ".join(f"{label(c)} ({s:.1f})" for c, s in weak[:3])
        reasons.append(f"Your lowest scores under the bar of 3 are {listed}.")
    if option.planned is not None and option.interview_type not in done:
        reasons.append(
            f"Your gap analysis plan has this session and you have not done it yet: "
            f"{option.planned.reason}"
        )
    difficulty = option.planned.difficulty if option.planned else Difficulty.REALISTIC
    return PlannedSession(
        priority=1,
        interview_type=option.interview_type,
        difficulty=difficulty,
        focus_topics=topics[:MAX_TOPICS],
        reason=" ".join(reasons),
    )


def _raise_the_bar(scores: Mapping[Competency, float]) -> PlannedSession:
    averages = []
    for itype, comps in COMPETENCIES_BY_TYPE.items():
        mine = [scores[c] for c in comps if c in scores]
        if mine:
            averages.append((sum(mine) / len(mine), itype))
    avg, itype = min(averages, key=lambda x: (x[0], x[1].value))
    lowest = sorted(
        (c for c in COMPETENCIES_BY_TYPE[itype] if c in scores), key=lambda c: scores[c]
    )
    return PlannedSession(
        priority=1,
        interview_type=itype,
        difficulty=Difficulty.TOUGH,
        focus_topics=[label(c).capitalize() for c in lowest[:3]],
        reason=(
            f"Every scored competency meets the bar. Your {TYPE_NAMES[itype]} average is the "
            f"lowest at {avg:.1f}, so practice it on Tough difficulty."
        ),
    )
