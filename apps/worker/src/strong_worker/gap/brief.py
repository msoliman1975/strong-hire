"""Interviewer brief builder (spec: Interviewer brief; IV-3 to IV-8).

    built = await build_brief(gateway, config, posting, resume, profile, gap=analysis)
    built.brief   # InterviewerBrief, the only thing the live interviewer reads

The planner model writes the questions (BriefDraft). Code decides everything else, so the
brief follows the rules even with a weak model:

- target competencies (4 to 6): the interview type's competencies, ranked by company weight,
  then by the weakest gap analysis score
- target values: the highest-weighted company values (none in generic mode)
- persona: the profile persona (or the generic one), adjusted for difficulty
- seniority bar: the profile's bar for the level, else a generic bar (IV-6)
- probe limit, pushback and curveball by difficulty (IV-3, IV-4); coach help by mode (IV-8)
- time plan per phase (IV-7), and a size limit so the live loop stays fast
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.profiles import ResolvedProfile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefDraft,
    BriefQuestion,
    Competency,
    Difficulty,
    GapAnalysis,
    InterviewerBrief,
    JobPosting,
    Level,
    Mode,
    PersonaBrief,
    Phase,
    PhaseTime,
    Resume,
    SessionConfig,
    Severity,
)
from strong_worker.gap.text import posting_text, resume_text

log = logging.getLogger(__name__)

PROMPT = "interviewer_brief"
PROMPT_INPUT = "interviewer_brief_input"
ATTEMPTS = 2
MAX_BRIEF_TOKENS = 1500
CHARS_PER_TOKEN = 4  # rough and conservative for English JSON
MAX_VALUES = 3
MAX_PROBE_AREAS = 5
MAX_HINTS = 3
MAX_TEXT = 240
MAX_HINT = 120
MAX_PATTERNS = 5

QUESTIONS_BY_DURATION = {30: 8, 45: 10}
COMPETENCIES_BY_DURATION = {30: 5, 45: 6}

PROBES_BY_DIFFICULTY = {Difficulty.FRIENDLY: 1, Difficulty.REALISTIC: 3, Difficulty.TOUGH: 3}
"""IV-3: up to 3 probes per question, fewer in Friendly."""

TONE_BY_DIFFICULTY = {
    Difficulty.FRIENDLY: "Warm and encouraging. Gives the candidate time and helps them settle.",
    Difficulty.REALISTIC: "Neutral and professional, like a real interviewer at this company.",
    Difficulty.TOUGH: "Direct and skeptical. Expects precise answers and does not fill silences.",
}
PUSHBACK_FRIENDLY = "Gentle. Asks for more detail but does not challenge the answer."
PUSHBACK_TOUGH = "Challenges assumptions and asks why not the simpler option."
DEFAULT_CURVEBALL = (
    "Midway, change one key constraint of the candidate's last answer and ask how their "
    "decision changes."
)

GENERIC_BARS = {
    Level.NEW_GRAD: (
        "New grad: solid fundamentals and clear reasoning on well-scoped tasks. "
        "Learns fast with guidance. Impact is on their own work."
    ),
    Level.MID: (
        "Mid level: owns features end to end with little guidance. Makes sound trade-offs "
        "inside one team."
    ),
    Level.SENIOR: (
        "Senior: leads projects across a team, sets technical or product direction, mentors "
        "others and handles ambiguity."
    ),
    Level.STAFF_PRINCIPAL: (
        "Staff or principal: shapes direction across several teams or the whole org. Owns "
        "long-term trade-offs and raises the bar of others."
    ),
}

# Minutes per phase (IV-7). Each plan adds up to the session length.
TIME_PLANS: dict[int, tuple[tuple[Phase, int], ...]] = {
    30: (
        (Phase.INTRO, 1),
        (Phase.SMALL_TALK, 2),
        (Phase.AGENDA, 1),
        (Phase.CORE, 21),
        (Phase.CANDIDATE_QUESTIONS, 4),
        (Phase.WRAP_UP, 1),
    ),
    45: (
        (Phase.INTRO, 1),
        (Phase.SMALL_TALK, 2),
        (Phase.AGENDA, 1),
        (Phase.CORE, 35),
        (Phase.CANDIDATE_QUESTIONS, 5),
        (Phase.WRAP_UP, 1),
    ),
}

_ID = re.compile(r"^[a-z0-9_-]+$")


class BriefError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuiltBrief:
    brief: InterviewerBrief
    model_version: str
    tokens: int
    flags: list[str] = field(default_factory=list)


def brief_tokens(brief: InterviewerBrief) -> int:
    return len(brief.model_dump_json(exclude_none=True)) // CHARS_PER_TOKEN + 1


def time_plan(duration_min: int) -> list[PhaseTime]:
    return [PhaseTime(phase=p, minutes=m) for p, m in TIME_PLANS[duration_min]]


def target_competencies(
    config: SessionConfig, profile: ResolvedProfile, gap: GapAnalysis | None
) -> list[Competency]:
    """4 to 6 competencies: by company weight, then the weakest in the gap analysis."""
    pool = list(COMPETENCIES_BY_TYPE[config.interview_type])
    scores = {c.competency: c.score for c in gap.competency_breakdown} if gap else {}
    ranked = sorted(pool, key=lambda c: (-profile.weight(c), scores.get(c, 50), pool.index(c)))
    count = min(len(pool), COMPETENCIES_BY_DURATION[config.duration_min])
    chosen = ranked[:count]
    senior = config.level in (Level.SENIOR, Level.STAFF_PRINCIPAL)
    if senior and Competency.SCOPE_AT_LEVEL in pool and Competency.SCOPE_AT_LEVEL not in chosen:
        chosen[-1] = Competency.SCOPE_AT_LEVEL  # IV-6: senior bars are about scope
    return chosen


def target_values(config: SessionConfig, profile: ResolvedProfile) -> list[str]:
    """Up to 3 company values: those the profile's patterns for this type probe, by weight."""
    if profile.profile is None:
        return []
    principles = profile.profile.values_framework.principles
    patterned = {
        v
        for q in profile.profile.question_patterns
        if q.interview_type == config.interview_type
        for v in q.values
    }
    ranked = sorted(principles, key=lambda p: (p.name not in patterned, -p.weight))
    return [p.name for p in ranked[:MAX_VALUES]]


def seniority_bar(config: SessionConfig, posting: JobPosting, profile: ResolvedProfile) -> str:
    if profile.profile is not None:
        bars = [b for b in profile.profile.bar_by_level if b.normalized_level == config.level]
        same_family = [b for b in bars if b.role_family == posting.role_family]
        bar = next(iter(same_family or bars), None)
        if bar is not None:
            return f"{bar.level_name} ({config.level.value}): {bar.scope_expectation}"[:400]
    return GENERIC_BARS[config.level]


def persona(config: SessionConfig, profile: ResolvedProfile) -> PersonaBrief:
    notes = profile.persona
    pushback = {
        Difficulty.FRIENDLY: PUSHBACK_FRIENDLY,
        Difficulty.REALISTIC: notes.pushback_style,
        Difficulty.TOUGH: f"{notes.pushback_style} {PUSHBACK_TOUGH}",
    }[config.difficulty]
    return PersonaBrief(
        tone=f"{notes.tone}. {TONE_BY_DIFFICULTY[config.difficulty]}"[:300],
        pushback_style=pushback[:300],
        closing_style=notes.closing_style[:300],
    )


def probe_areas(gap: GapAnalysis | None) -> list[str]:
    if gap is None:
        return []
    items = list(gap.probe_areas) + [g.summary for g in gap.gaps if g.severity == Severity.HIGH]
    out: list[str] = []
    for item in items:
        text = item.strip()[:100]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:MAX_PROBE_AREAS]


def build_messages(
    config: SessionConfig,
    posting: JobPosting,
    resume: Resume | None,
    profile: ResolvedProfile,
    gap: GapAnalysis | None,
) -> list[Message]:
    comps = target_competencies(config, profile, gap)
    values = target_values(config, profile)
    signals = []
    patterns = []
    if profile.profile is not None:
        for p in profile.profile.values_framework.principles:
            if p.name in values:
                signals.append(f"{p.name}: {'; '.join(p.evidence_signals[:2])}")
        patterns = [
            f"{q.theme}: {q.pattern}"
            for q in profile.profile.question_patterns
            if q.interview_type == config.interview_type
        ][:MAX_PATTERNS]
    gaps = [f"[{g.severity.value}] {g.summary}" for g in (gap.gaps if gap else [])][:6]
    tough = config.difficulty == Difficulty.TOUGH
    return [
        load_prompt(Role.PLANNER, PROMPT).message("system"),
        load_prompt(Role.PLANNER, PROMPT_INPUT).message(
            "user",
            interview_type=config.interview_type.value,
            level=config.level.value,
            seniority_bar=seniority_bar(config, posting, profile),
            difficulty=config.difficulty.value,
            mode=config.mode.value,
            duration=config.duration_min,
            question_count=QUESTIONS_BY_DURATION[config.duration_min],
            company=profile.company_name if not profile.generic else "generic mode (no profile)",
            competencies=", ".join(c.value for c in comps),
            values="\n".join(signals) or "(none: generic mode, leave values empty)",
            patterns="\n".join(patterns) or "(none)",
            curveball="Write one curveball." if tough else "Set curveball to null.",
            probe_areas="\n".join(probe_areas(gap)) or "(none)",
            gaps="\n".join(gaps) or "(none)",
            job=posting_text(posting),
            resume=resume_text(resume) if resume else "(no resume)",
        ),
    ]


def assemble(
    draft: BriefDraft,
    config: SessionConfig,
    posting: JobPosting,
    profile: ResolvedProfile,
    gap: GapAnalysis | None,
) -> tuple[InterviewerBrief, list[str]]:
    """Build the InterviewerBrief from the model's draft. Pure: same inputs, same brief."""
    flags: list[str] = []
    comps = target_competencies(config, profile, gap)
    values = target_values(config, profile)
    questions = _clean_questions(draft.questions, comps, values, flags)
    questions = questions[: QUESTIONS_BY_DURATION[config.duration_min]]
    if len(questions) < 6:
        raise BriefError(f"the draft has {len(questions)} usable questions; 6 are needed")
    _cover(questions, comps)
    questions = [q.model_copy(update={"priority": i}) for i, q in enumerate(questions, start=1)]

    tough = config.difficulty == Difficulty.TOUGH
    curveball = None
    if tough:
        curveball = (draft.curveball or "").strip()[:MAX_TEXT] or DEFAULT_CURVEBALL
    brief = InterviewerBrief(
        session=config,
        company_name=None if profile.generic else profile.company_name,
        generic_mode=profile.generic,
        profile_version=profile.version,
        target_competencies=comps,
        target_values=values,
        questions=questions,
        probe_areas=probe_areas(gap),
        persona=persona(config, profile),
        max_probes_per_question=PROBES_BY_DIFFICULTY[config.difficulty],
        curveball=curveball,
        seniority_bar=seniority_bar(config, posting, profile),
        pushback=tough,
        coach_help=config.mode == Mode.COACH,
        time_plan=time_plan(config.duration_min),
    )
    return _fit(brief, flags), flags


async def build_brief(
    gateway: ModelGateway,
    config: SessionConfig,
    posting: JobPosting,
    resume: Resume | None,
    profile: ResolvedProfile,
    *,
    gap: GapAnalysis | None = None,
) -> BuiltBrief:
    """Ask the planner for questions, then build and check the brief in code. Retries once."""
    messages = build_messages(config, posting, resume, profile, gap)
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            done = await gateway.complete(Role.PLANNER, messages, output_type=BriefDraft)
            brief, flags = assemble(done.output, config, posting, profile, gap)
        except Exception as exc:  # gateway, validation or a draft with too few questions
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}"[:300])
            log.warning("planner brief call failed (%s), attempt %d", type(exc).__name__, attempt)
            continue
        version = f"{done.model} {' '.join(done.prompt_refs)}".strip()[:200]
        return BuiltBrief(brief, version, brief_tokens(brief), flags)
    raise BriefError(f"Brief failed after {ATTEMPTS} attempts: " + " | ".join(errors))


# --- helpers ---------------------------------------------------------------------------------


def _clean_questions(
    draft: list[BriefQuestion], comps: list[Competency], values: list[str], flags: list[str]
) -> list[BriefQuestion]:
    out: list[BriefQuestion] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    for q in sorted(draft, key=lambda q: q.priority):
        text = q.text.strip()[:MAX_TEXT]
        if text.lower() in seen_text:
            flags.append(f"duplicate_question: {q.id}")
            continue
        seen_text.add(text.lower())
        qid = q.id if _ID.match(q.id) and q.id not in seen_ids else f"q{len(out) + 1}"
        while qid in seen_ids:
            qid = f"{qid}x"
        seen_ids.add(qid)
        kept = [c for c in q.competencies if c in comps]
        if not kept:
            kept = [_least_covered(out, comps)]
            flags.append(f"competency_reassigned: {qid}")
        out.append(
            q.model_copy(
                update={
                    "id": qid,
                    "text": text,
                    "competencies": list(dict.fromkeys(kept)),
                    "values": [v for v in dict.fromkeys(q.values) if v in values],
                    "probe_hints": [h.strip()[:MAX_HINT] for h in q.probe_hints if h.strip()][
                        :MAX_HINTS
                    ],
                }
            )
        )
    return out


def _least_covered(questions: list[BriefQuestion], comps: list[Competency]) -> Competency:
    counts = {c: 0 for c in comps}
    for q in questions:
        for c in q.competencies:
            if c in counts:
                counts[c] += 1
    return min(comps, key=lambda c: (counts[c], comps.index(c)))


def _cover(questions: list[BriefQuestion], comps: list[Competency]) -> None:
    """Make every target competency appear in at least one question (in place)."""
    covered = {c for q in questions for c in q.competencies}
    for i, comp in enumerate(c for c in comps if c not in covered):
        q = questions[i % len(questions)]
        questions[i % len(questions)] = q.model_copy(
            update={"competencies": [*q.competencies, comp]}
        )


def _fit(brief: InterviewerBrief, flags: list[str]) -> InterviewerBrief:
    """Trim the brief until it is under MAX_BRIEF_TOKENS: hints first, then extra questions."""
    while brief_tokens(brief) > MAX_BRIEF_TOKENS:
        questions = brief.questions
        longest = max(questions, key=lambda q: len(q.probe_hints))
        if len(longest.probe_hints) > 1:
            trimmed = [q.model_copy(update={"probe_hints": q.probe_hints[:1]}) for q in questions]
            flags.append("trimmed_probe_hints")
        elif len(questions) > 6:
            trimmed = questions[:-1]
            _cover(trimmed, brief.target_competencies)
            flags.append("dropped_question")
        else:
            trimmed = [
                q.model_copy(update={"text": q.text[:120], "probe_hints": []}) for q in questions
            ]
            flags.append("shortened_questions")
            brief = brief.model_copy(update={"questions": trimmed})
            break
        brief = brief.model_copy(update={"questions": trimmed})
    return InterviewerBrief.model_validate(brief.model_dump())
