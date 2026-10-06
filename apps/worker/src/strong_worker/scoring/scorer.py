"""The scorer: a finished transcript in, a Scorecard out (FB-1, FB-2).

Steps:
1. One scorer-role call reads the transcript, the brief and the profile, and returns per-question
   rubric scores (1 to 4) with justifications and quotes (prompt scorer/rubric).
2. Every quote is checked against the candidate's words (quotes.QuoteChecker). Bad quotes are
   dropped. If a score loses all its quotes, the scorer asks once more (scorer/requote). A score
   that still has no valid quote is dropped.
3. Code averages the per-question scores per competency and per company value, and computes the
   hire signal with the profile weights and the hard rules (signal.compute_hire_signal).
4. A second call writes the 3 to 5 sentence rationale for the computed signal
   (scorer/rationale). If it names another signal or has the wrong length after one retry, a
   rationale built in code from the same facts is used.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.profiles import ResolvedProfile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefQuestion,
    Competency,
    CompetencyScore,
    HireSignal,
    InterviewerBrief,
    Phase,
    QuestionScore,
    Scorecard,
    Speaker,
    Turn,
    ValueScore,
)
from strong_worker.scoring.levels import level_expectations
from strong_worker.scoring.quotes import QuoteChecker
from strong_worker.scoring.signal import SignalResult, compute_hire_signal, rubric_point

log = logging.getLogger(__name__)

ROLE = Role.SCORER
MAX_QUOTES = 3
# Share of the context window the transcript may use; the rest is for the rubric and the reply.
TRANSCRIPT_SHARE = 0.55
CHARS_PER_TOKEN = 4
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_SIGNAL_NAMES = sorted((s.value for s in HireSignal), key=len, reverse=True)


class ScoringError(RuntimeError):
    """The transcript cannot be scored. The message says why, in plain words."""


@dataclass
class ScoringOutcome:
    scorecard: Scorecard
    signal: SignalResult
    competency_averages: dict[Competency, float]
    value_averages: dict[str, float]
    dropped_quotes: list[str] = field(default_factory=list)
    dropped_scores: list[str] = field(default_factory=list)
    reasked: bool = False
    rationale_source: str = "model"  # "model" or "code"
    model_calls: int = 0
    seconds: float = 0.0


# --- the cleaned model output ----------------------------------------------------------------


@dataclass
class _Question:
    ref: str
    text: str
    scores: dict[Competency, CompetencyScore] = field(default_factory=dict)
    values: dict[str, ValueScore] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    questions: dict[str, _Question] = field(default_factory=dict)
    overall: dict[Competency, CompetencyScore] = field(default_factory=dict)
    overall_values: dict[str, ValueScore] = field(default_factory=dict)
    bad_quotes: list[str] = field(default_factory=list)
    lost: list[str] = field(default_factory=list)
    """Scores that had quotes, all of them invalid: 'q1/ownership'."""

    def merge_missing(self, other: _Draft) -> None:
        """Add the scores this draft lost and the other one has with valid quotes."""
        for ref, q in other.questions.items():
            mine = self.questions.setdefault(ref, _Question(ref, q.text))
            for c, cs in q.scores.items():
                mine.scores.setdefault(c, cs)
            for v, vs in q.values.items():
                mine.values.setdefault(v, vs)
            mine.strengths = mine.strengths or q.strengths
            mine.misses = mine.misses or q.misses
        for c, cs in other.overall.items():
            self.overall.setdefault(c, cs)
        for v, vs in other.overall_values.items():
            self.overall_values.setdefault(v, vs)
        self.lost = [k for k in self.lost if not self._has(k)]

    def _has(self, key: str) -> bool:
        ref, _, name = key.partition("/")
        if ref == "overall":
            return any(c.value == name for c in self.overall) or name in self.overall_values
        q = self.questions.get(ref)
        if q is None:
            return False
        return any(c.value == name for c in q.scores) or name in q.values


class SessionScorer:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def score(
        self, brief: InterviewerBrief, turns: Sequence[Turn], profile: ResolvedProfile
    ) -> ScoringOutcome:
        started = time.perf_counter()
        if not any(t.speaker == Speaker.CANDIDATE and t.text.strip() for t in turns):
            raise ScoringError("The transcript has no candidate answers to score.")
        checker = QuoteChecker(turns)
        asked = _asked_questions(brief, turns)
        allowed_values = _allowed_values(brief, profile)
        rubric = load_prompt(ROLE, "rubric")
        messages = [
            rubric.message("system"),
            self._input(brief, turns, profile, asked, allowed_values),
        ]
        calls = 1
        done = await self.gateway.complete(ROLE, messages, output_type=Scorecard)
        draft = _clean(done.output, checker, brief, asked, allowed_values)
        dropped_quotes = list(draft.bad_quotes)
        reasked = False
        if draft.lost or not _any_scores(draft):
            reasked = True
            problems = "\n".join(f"- {q}" for q in dict.fromkeys(draft.bad_quotes)) or "- (none)"
            retry = [
                *messages,
                Message(role="assistant", content=done.output.model_dump_json()),
                load_prompt(ROLE, "requote").message("user", problems=problems),
            ]
            calls += 1
            again = await self.gateway.complete(ROLE, retry, output_type=Scorecard)
            second = _clean(again.output, checker, brief, asked, allowed_values)
            dropped_quotes += second.bad_quotes
            draft.merge_missing(second)

        comp_scores, comp_avgs = _competency_scores(draft)
        if not comp_scores:
            raise ScoringError(
                "No competency score has a quote that appears in the transcript, so the "
                "session cannot be scored."
            )
        value_scores, value_avgs = _value_scores(draft)
        signal = compute_hire_signal(comp_avgs, profile, value_avgs)
        per_question = _per_question(draft, asked)

        rationale, source, rationale_calls = await self._rationale(
            brief, signal, comp_avgs, value_avgs, profile, per_question
        )
        calls += rationale_calls
        card = Scorecard(
            hire_signal=signal.signal,
            rationale=rationale,
            competency_scores=comp_scores,
            value_scores=value_scores,
            per_question=per_question,
            scorer_model=done.model,
            rubric_version=rubric.ref,
        )
        outcome = ScoringOutcome(
            scorecard=card,
            signal=signal,
            competency_averages=comp_avgs,
            value_averages=value_avgs,
            dropped_quotes=dropped_quotes,
            dropped_scores=list(draft.lost),
            reasked=reasked,
            rationale_source=source,
            model_calls=calls,
            seconds=round(time.perf_counter() - started, 3),
        )
        log.info(
            "scored: signal=%s average=%.2f dropped_quotes=%d dropped_scores=%d reasked=%s "
            "calls=%d seconds=%.2f",
            signal.signal.value,
            signal.average,
            len(dropped_quotes),
            len(draft.lost),
            reasked,
            calls,
            outcome.seconds,
        )
        return outcome

    # --- prompts ------------------------------------------------------------------------------

    def _input(
        self,
        brief: InterviewerBrief,
        turns: Sequence[Turn],
        profile: ResolvedProfile,
        asked: list[BriefQuestion],
        allowed_values: set[str],
    ) -> Message:
        window = self.gateway.capabilities(ROLE).context_window
        budget = int(window * TRANSCRIPT_SHARE * CHARS_PER_TOKEN)
        return load_prompt(ROLE, "rubric_input").message(
            "user",
            interview_type=brief.session.interview_type.value,
            level=brief.session.level.value,
            company=profile.company_name if not profile.generic else "generic mode",
            level_expectations=level_expectations(brief.session.level, profile),
            competencies=", ".join(c.value for c in _scored_competencies(brief, asked)),
            values=_values_text(profile, allowed_values),
            questions="\n".join(
                f"{q.id}: {q.text} [{', '.join(c.value for c in q.competencies)}] "
                f"{{{', '.join(v for v in q.values if v in allowed_values)}}}"
                for q in asked
            )
            or "(no question was asked)",
            transcript=render_transcript(turns, budget),
        )

    async def _rationale(
        self,
        brief: InterviewerBrief,
        signal: SignalResult,
        comp_avgs: dict[Competency, float],
        value_avgs: dict[str, float],
        profile: ResolvedProfile,
        per_question: list[QuestionScore],
    ) -> tuple[str, str, int]:
        strengths = [s for q in per_question for s in q.strengths][:6]
        misses = [m for q in per_question for m in q.misses][:6]
        user = load_prompt(ROLE, "rationale_input").message(
            "user",
            hire_signal=signal.signal.value,
            interview_type=brief.session.interview_type.value,
            level=brief.session.level.value,
            average=f"{signal.average:.2f}",
            rules=" ".join(signal.rules) or "none",
            competencies="\n".join(
                f"- {c.value}: {a:.1f} (weight {profile.weight(c):g})"
                for c, a in sorted(comp_avgs.items(), key=lambda x: -x[1])
            ),
            values="\n".join(f"- {v}: {a:.1f}" for v, a in value_avgs.items())
            or "none (generic mode or no value scored)",
            strengths="\n".join(f"- {s}" for s in strengths) or "- none noted",
            misses="\n".join(f"- {m}" for m in misses) or "- none noted",
        )
        messages = [load_prompt(ROLE, "rationale").message("system"), user]
        for attempt in (1, 2):
            done = await self.gateway.complete(ROLE, messages)
            text = check_rationale(done.output, signal.signal)
            if text is not None:
                return text, "model", attempt
        return fallback_rationale(signal, comp_avgs, value_avgs), "code", 2


# --- helpers ---------------------------------------------------------------------------------


def render_transcript(turns: Sequence[Turn], max_chars: int | None = None) -> str:
    """The transcript as lines. Over budget, intro and small talk go first, then wrap-up."""

    def line(t: Turn) -> str:
        who = "Interviewer" if t.speaker == Speaker.INTERVIEWER else "Candidate"
        ref = f" [{t.question_ref}]" if t.question_ref else ""
        return f"{who}{ref}: {t.text.strip()}"

    kept = list(turns)
    text = "\n".join(line(t) for t in kept)
    for phase in (Phase.SMALL_TALK, Phase.INTRO, Phase.AGENDA, Phase.WRAP_UP):
        if max_chars is None or len(text) <= max_chars:
            break
        kept = [t for t in kept if t.phase != phase]
        text = "\n".join(line(t) for t in kept)
    return text or "(empty transcript)"


def _asked_questions(brief: InterviewerBrief, turns: Sequence[Turn]) -> list[BriefQuestion]:
    by_id = {q.id: q for q in brief.questions}
    seen: dict[str, None] = {}
    for t in turns:
        if t.phase == Phase.CORE and t.question_ref in by_id:
            seen.setdefault(t.question_ref, None)
    return [by_id[ref] for ref in seen]


def _scored_competencies(brief: InterviewerBrief, asked: list[BriefQuestion]) -> list[Competency]:
    out = dict.fromkeys(c for q in asked for c in q.competencies)
    for c in brief.target_competencies:
        out.setdefault(c, None)
    return list(out)


def _allowed_values(brief: InterviewerBrief, profile: ResolvedProfile) -> set[str]:
    """Company values the scorer may score: in the brief and in the session's profile."""
    if brief.generic_mode or profile.generic:
        return set()
    return set(brief.target_values) & set(profile.value_weights)


def _values_text(profile: ResolvedProfile, allowed: set[str]) -> str:
    framework = profile.values_framework
    if not allowed or framework is None:
        return "None. This session runs in generic mode, or the brief targets no company value."
    lines = [f"{framework.name}:"]
    for p in framework.principles:
        if p.name in allowed:
            signals = "; ".join(p.evidence_signals)
            lines.append(f"- {p.name}: {p.description} Evidence sounds like: {signals}")
    return "\n".join(lines)


def _clean(
    card: Scorecard,
    checker: QuoteChecker,
    brief: InterviewerBrief,
    asked: list[BriefQuestion],
    allowed_values: set[str],
) -> _Draft:
    """Keep scores for asked questions, allowed competencies and values, and valid quotes."""
    draft = _Draft()
    type_comps = set(COMPETENCIES_BY_TYPE[brief.session.interview_type])
    asked_by_id = {q.id: q for q in asked}

    def keep_comp(key: str, s: CompetencyScore) -> CompetencyScore | None:
        good, bad = checker.keep_valid(s.quotes)
        draft.bad_quotes += bad
        if not good:
            draft.lost.append(key)
            return None
        return s.model_copy(update={"quotes": good[:MAX_QUOTES]})

    def keep_value(key: str, s: ValueScore) -> ValueScore | None:
        good, bad = checker.keep_valid(s.quotes)
        draft.bad_quotes += bad
        if not good:
            draft.lost.append(key)
            return None
        return s.model_copy(update={"quotes": good[:MAX_QUOTES]})

    for qs in card.per_question:
        bq = asked_by_id.get(qs.question_ref)
        if bq is None:
            continue  # a question that was not asked
        q = draft.questions.setdefault(bq.id, _Question(bq.id, bq.text))
        for s in qs.scores:
            if s.competency in type_comps and s.competency not in q.scores:
                kept = keep_comp(f"{bq.id}/{s.competency.value}", s)
                if kept is not None:
                    q.scores[s.competency] = kept
        for v in qs.value_scores:
            if v.value in allowed_values and v.value not in q.values:
                kept_v = keep_value(f"{bq.id}/{v.value}", v)
                if kept_v is not None:
                    q.values[v.value] = kept_v
        q.strengths = [s for s in qs.strengths if s.strip()][:4]
        q.misses = [m for m in qs.misses if m.strip()][:4]
    for s in card.competency_scores:
        if s.competency in type_comps and s.competency not in draft.overall:
            kept = keep_comp(f"overall/{s.competency.value}", s)
            if kept is not None:
                draft.overall[s.competency] = kept
    for v in card.value_scores:
        if v.value in allowed_values and v.value not in draft.overall_values:
            kept_v = keep_value(f"overall/{v.value}", v)
            if kept_v is not None:
                draft.overall_values[v.value] = kept_v
    return draft


def _any_scores(draft: _Draft) -> bool:
    return bool(draft.overall) or any(q.scores for q in draft.questions.values())


def _mean(values: list[int]) -> float:
    return sum(values) / len(values)


def _competency_scores(
    draft: _Draft,
) -> tuple[list[CompetencyScore], dict[Competency, float]]:
    """One overall score per competency: the mean of its per-question scores.

    A competency the model scored only overall (no per-question score) keeps that score.
    """
    per: dict[Competency, list[CompetencyScore]] = defaultdict(list)
    for q in draft.questions.values():
        for c, s in q.scores.items():
            per[c].append(s)
    averages: dict[Competency, float] = {}
    out: list[CompetencyScore] = []
    for c in dict.fromkeys([*per, *draft.overall]):
        items = per.get(c, [])
        overall = draft.overall.get(c)
        if items:
            avg = _mean([s.score for s in items])
            quotes = list(dict.fromkeys(q for s in items for q in s.quotes))
            justification = (
                overall.justification
                if overall is not None
                else " ".join(dict.fromkeys(s.justification for s in items))
            )
        else:
            assert overall is not None
            avg = float(overall.score)
            quotes = overall.quotes
            justification = overall.justification
        averages[c] = avg
        out.append(
            CompetencyScore(
                competency=c,
                score=rubric_point(avg),
                justification=justification,
                quotes=quotes[:MAX_QUOTES],
            )
        )
    return out, averages


def _value_scores(draft: _Draft) -> tuple[list[ValueScore], dict[str, float]]:
    per: dict[str, list[ValueScore]] = defaultdict(list)
    for q in draft.questions.values():
        for v, s in q.values.items():
            per[v].append(s)
    averages: dict[str, float] = {}
    out: list[ValueScore] = []
    for v in dict.fromkeys([*per, *draft.overall_values]):
        items = per.get(v, [])
        overall = draft.overall_values.get(v)
        if items:
            avg = _mean([s.score for s in items])
            quotes = list(dict.fromkeys(q for s in items for q in s.quotes))
            justification = (
                overall.justification
                if overall is not None
                else " ".join(dict.fromkeys(s.justification for s in items))
            )
        else:
            assert overall is not None
            avg = float(overall.score)
            quotes = overall.quotes
            justification = overall.justification
        averages[v] = avg
        out.append(
            ValueScore(
                value=v,
                score=rubric_point(avg),
                justification=justification,
                quotes=quotes[:MAX_QUOTES],
            )
        )
    return out, averages


def _per_question(draft: _Draft, asked: list[BriefQuestion]) -> list[QuestionScore]:
    out = []
    for bq in asked:
        q = draft.questions.get(bq.id)
        if q is None or not q.scores:
            continue
        out.append(
            QuestionScore(
                question_ref=bq.id,
                question_text=bq.text,
                scores=list(q.scores.values()),
                value_scores=list(q.values.values()),
                strengths=q.strengths,
                misses=q.misses,
            )
        )
    return out


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(" ".join(text.split())) if s.strip()]


def named_signals(text: str) -> set[HireSignal]:
    """Hire signals the text names. 'Lean No Hire' is not also read as 'No Hire' or 'Hire'."""
    found: set[HireSignal] = set()
    rest = text
    for name in _SIGNAL_NAMES:
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        if pattern.search(rest):
            found.add(HireSignal(name))
            rest = pattern.sub(" ", rest)
    return found


def check_rationale(text: str, signal: HireSignal) -> str | None:
    """The rationale if it has 3 to 5 sentences and names no other signal, else None."""
    parts = sentences(text.strip())
    if len(parts) > 5:
        parts = parts[:5]
    if len(parts) < 3:
        return None
    if named_signals(" ".join(parts)) - {signal}:
        return None
    return " ".join(parts)


def _label(name: str) -> str:
    return name.replace("_", " ")


def fallback_rationale(
    signal: SignalResult, comp_avgs: dict[Competency, float], value_avgs: dict[str, float]
) -> str:
    """A plain rationale from the computed facts, used when the model's text fails the checks."""
    ranked = sorted(comp_avgs.items(), key=lambda x: (-x[1], x[0].value))
    best, worst = ranked[0], ranked[-1]
    out = [
        f"The signal is {signal.signal.value}, from a weighted average of "
        f"{signal.average:.1f} out of 4.",
        f"The strongest competency was {_label(best[0].value)} at {best[1]:.1f}.",
        f"The weakest competency was {_label(worst[0].value)} at {worst[1]:.1f}.",
    ]
    if value_avgs:
        top = max(value_avgs.items(), key=lambda x: x[1])
        out.append(f"Among the company values, {top[0]} scored highest at {top[1]:.1f}.")
    out += signal.rules[: 5 - len(out)]
    return " ".join(out[:5])
