"""Interviewer brief builder (spec: Interviewer brief; IV-3 to IV-8).

    built = await build_brief(gateway, config, posting, resume, profile, gap=analysis)
    built.brief   # InterviewerBrief, the only thing the live interviewer reads

The planner model writes the questions (BriefDraft). Code decides everything else, so the
brief follows the rules even with a weak model:

- target competencies (4 to 6, 2 in a mini): the interview type's competencies, ranked by
  company weight, then by the weakest gap analysis score
- target values: the highest-weighted company values (none in generic mode)
- persona: the profile persona (or the generic one), adjusted for difficulty
- seniority bar: the profile's bar for the level, else a generic bar (IV-6)
- probe limit, pushback and curveball by difficulty (IV-3, IV-4); coach help by mode (IV-8)
- time plan per phase (IV-7), and a size limit so the live loop stays fast

A 10-minute mini interview gets 3 questions, 2 competencies, no curveball, at most 1 probe per
question, and a time plan with no small talk and no candidate questions.

Custom sessions (docs/custom-interview-spec.md, CU-1, CU-2, CU-4, CU-12):

- The candidate's own questions are copied into the brief in code (`source=candidate`), with
  their text trimmed only, never rewritten or dropped. They keep their category, competencies,
  must-ask and verbatim flags. The planner model only sees them as quoted data.
- The planner writes questions for the remaining slots (QUESTIONS_BY_DURATION minus the own
  questions). Code gives each slot to the category furthest below its time share
  (share x question count, own questions included), and takes that category's best planner
  question. A planner question without a valid category gets one in code: the category its
  competencies belong to, else the least covered one (flag `category_assigned`).
- Target competencies come from the session pool (`session_competencies`): the own questions'
  competencies first, then those that match a focus chip, then company weight and the weakest
  gap scores, with at least one per category.
- List order is the asking order: categories in the candidate's order; within a category own
  and planner questions alternate (own must-ask questions first among the own ones). Priority
  is importance: must-ask questions get 1..m, the rest follow in list order.
- Trimming for the token limit never touches an own question.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.profiles import ResolvedProfile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    MINI_MAX_PROBES,
    BriefDraft,
    BriefQuestion,
    Competency,
    CustomSessionSpec,
    Difficulty,
    DraftQuestion,
    GapAnalysis,
    InterviewerBrief,
    InterviewType,
    JobPosting,
    Level,
    Mode,
    PersonaBrief,
    Phase,
    PhaseTime,
    QuestionSource,
    Resume,
    SessionConfig,
    Severity,
    session_competencies,
)
from strong_core.schemas.session import FULL_MIN_COMPETENCIES
from strong_worker.gap.text import posting_text, resume_text

log = logging.getLogger(__name__)

PROMPT = "interviewer_brief"
PROMPT_INPUT = "interviewer_brief_input"
PROMPT_CUSTOM = "interviewer_brief_custom"
PROMPT_CUSTOM_INPUT = "interviewer_brief_custom_input"
ATTEMPTS = 2
MAX_BRIEF_TOKENS = 1500
CHARS_PER_TOKEN = 4  # rough and conservative for English JSON
MAX_VALUES = 3
MAX_PROBE_AREAS = 5
MAX_HINTS = 3
MAX_TEXT = 240
MAX_HINT = 120
MAX_PATTERNS = 5
MAX_SAMPLES = 4
MAX_SAMPLE_ANSWER = 200

QUESTIONS_BY_DURATION = {10: 3, 30: 8, 45: 10}
COMPETENCIES_BY_DURATION = {10: 2, 30: 5, 45: 6}
MIN_QUESTIONS_BY_DURATION = {10: 3, 30: 6, 45: 6}
# What the planner is asked to write. BriefDraft needs at least 6, so a mini asks for 6 and
# keeps the 3 with the best priority.
DRAFT_QUESTIONS_BY_DURATION = {10: 6, 30: 8, 45: 10}
# Custom: the planner writes a few more than the open slots, so each category has a choice.
DRAFT_SPARE = 2
DRAFT_MIN, DRAFT_MAX = 6, 12  # BriefDraft limits

PROBES_BY_DIFFICULTY = {Difficulty.FRIENDLY: 1, Difficulty.REALISTIC: 2, Difficulty.TOUGH: 3}
"""IV-3: up to 3 probes per question, fewer in Friendly. Same values as the P07 interviewer."""

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
    10: (
        (Phase.INTRO, 1),  # greeting (one small-talk line at most) and a one-sentence agenda
        (Phase.SMALL_TALK, 0),
        (Phase.AGENDA, 0),
        (Phase.CORE, 8),
        (Phase.CANDIDATE_QUESTIONS, 0),  # 0 minutes: the controller skips this phase
        (Phase.WRAP_UP, 1),
    ),
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
    """Rough token count of the brief. A Custom session's own questions are in `questions`, so
    their copy in session.custom is not counted twice."""
    exclude: dict[str, Any] = {"session": {"custom": {"questions"}}}
    return len(brief.model_dump_json(exclude_none=True, exclude=exclude)) // CHARS_PER_TOKEN + 1


def session_categories(config: SessionConfig) -> list[InterviewType]:
    """The question categories of a session: a Custom session's, in the candidate's order."""
    if config.custom is not None:
        return [c.category for c in config.custom.categories]
    return [config.interview_type]


def time_plan(duration_min: int) -> list[PhaseTime]:
    return [PhaseTime(phase=p, minutes=m) for p, m in TIME_PLANS[duration_min]]


def target_competencies(
    config: SessionConfig, profile: ResolvedProfile, gap: GapAnalysis | None
) -> list[Competency]:
    """4 to 6 competencies (2 in a mini): by company weight, then the weakest gap scores."""
    if config.custom is not None:
        return _custom_targets(config, config.custom, profile, gap)
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
    kinds = session_categories(config)
    patterned = {
        v for q in profile.profile.question_patterns if q.interview_type in kinds for v in q.values
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


def sample_questions(
    config: SessionConfig, profile: ResolvedProfile, comps: list[Competency]
) -> list[str]:
    """Up to 4 reported questions for this interview type (a Custom session's categories), those
    on target competencies first."""
    if profile.profile is None:
        return []
    kinds = session_categories(config)
    samples = [q for q in profile.profile.sample_questions if q.interview_type in kinds]
    samples.sort(key=lambda q: not set(q.competencies) & set(comps))
    tag = config.custom is not None
    return [
        f"- {f'[{q.interview_type.value}] ' if tag else ''}{q.question} "
        f"(strong answer: {q.strong_answer[:MAX_SAMPLE_ANSWER]})"
        for q in samples[:MAX_SAMPLES]
    ]


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
    if config.custom is not None:
        return _custom_messages(config, config.custom, posting, resume, profile, gap)
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
    curveball = config.difficulty == Difficulty.TOUGH and not config.is_mini
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
            question_count=DRAFT_QUESTIONS_BY_DURATION[config.duration_min],
            company=profile.company_name if not profile.generic else "generic mode (no profile)",
            competencies=", ".join(c.value for c in comps),
            values="\n".join(signals) or "(none: generic mode, leave values empty)",
            patterns="\n".join(patterns) or "(none)",
            sample_questions="\n".join(sample_questions(config, profile, comps)) or "(none)",
            curveball="Write one curveball." if curveball else "Set curveball to null.",
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
    needed = MIN_QUESTIONS_BY_DURATION[config.duration_min]
    if config.custom is not None:
        questions, comps = _custom_questions(draft, config, config.custom, comps, values, flags)
        if len(questions) < needed:
            raise BriefError(
                f"the draft has {len(questions)} usable questions; {needed} are needed"
            )
    else:
        questions = _clean_questions(draft.questions, comps, values, flags)
        questions = questions[: QUESTIONS_BY_DURATION[config.duration_min]]
        if len(questions) < needed:
            raise BriefError(
                f"the draft has {len(questions)} usable questions; {needed} are needed"
            )
        _cover(questions, comps)
        questions = [q.model_copy(update={"priority": i}) for i, q in enumerate(questions, start=1)]

    tough = config.difficulty == Difficulty.TOUGH
    curveball = None
    if tough and not config.is_mini:
        curveball = (draft.curveball or "").strip()[:MAX_TEXT] or DEFAULT_CURVEBALL
    probes = PROBES_BY_DIFFICULTY[config.difficulty]
    if config.is_mini:
        probes = min(probes, MINI_MAX_PROBES)
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
        max_probes_per_question=probes,
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
    draft: list[DraftQuestion], comps: list[Competency], values: list[str], flags: list[str]
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
            BriefQuestion(
                id=qid,
                text=text,
                competencies=list(dict.fromkeys(kept)),
                values=[v for v in dict.fromkeys(q.values) if v in values],
                priority=q.priority,
                probe_hints=[h.strip()[:MAX_HINT] for h in q.probe_hints if h.strip()][:MAX_HINTS],
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
    """Trim the brief until it is under MAX_BRIEF_TOKENS: hints first, then extra questions,
    then the question texts. A Custom session's own questions are never changed or dropped."""
    custom = brief.session.custom
    while brief_tokens(brief) > MAX_BRIEF_TOKENS:
        questions = brief.questions
        targets = list(brief.target_competencies)
        planner = [q for q in questions if q.source == QuestionSource.PLANNER]
        longest = max(questions, key=lambda q: len(q.probe_hints))
        if len(longest.probe_hints) > 1:
            trimmed = [q.model_copy(update={"probe_hints": q.probe_hints[:1]}) for q in questions]
            flags.append("trimmed_probe_hints")
        elif planner and len(questions) > MIN_QUESTIONS_BY_DURATION[brief.session.duration_min]:
            drop = _drop_choice(planner, questions, custom)
            trimmed = [q for q in questions if q.id != drop.id]
            if custom is None:
                _cover(trimmed, targets)
            else:
                trimmed = _custom_order(trimmed, custom)
                _cover_custom(trimmed, targets, flags)
            flags.append("dropped_question")
        else:
            trimmed = [
                q
                if q.source == QuestionSource.CANDIDATE
                else q.model_copy(update={"text": q.text[:120], "probe_hints": []})
                for q in questions
            ]
            flags.append("shortened_questions")
            brief = brief.model_copy(update={"questions": trimmed})
            break
        brief = brief.model_copy(update={"questions": trimmed, "target_competencies": targets})
    if brief_tokens(brief) > MAX_BRIEF_TOKENS:
        # Only very long own questions get here. Their text is never cut (CU-4).
        flags.append("over_token_limit")
        log.warning("brief has %d tokens after trimming", brief_tokens(brief))
    return InterviewerBrief.model_validate(brief.model_dump())


def _drop_choice(
    planner: list[BriefQuestion],
    questions: list[BriefQuestion],
    custom: CustomSessionSpec | None,
) -> BriefQuestion:
    """The planner question to drop: the least important one; in a Custom session, from the
    category furthest above its time share."""
    if custom is None:
        return max(planner, key=lambda q: q.priority)
    counts = Counter(q.category for q in questions)
    share = {c.category: c.share for c in custom.categories}

    def surplus(q: BriefQuestion) -> float:
        if q.category is None:
            return 0.0
        return counts[q.category] - share[q.category] * len(questions)

    return max(planner, key=lambda q: (surplus(q), q.priority))


# --- Custom sessions (CU-1, CU-2, CU-4, CU-12) -----------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
STEM = 5
"""A focus chip names a competency when a word of each starts with the same 5 letters."""


def _stems(text: str) -> set[str]:
    return {w[:STEM] for w in _WORD.findall(text.lower().replace("_", " ")) if len(w) >= 4}


def _focus_matches(spec: CustomSessionSpec) -> set[Competency]:
    """Competencies whose name shares a word with a focus chip of their category (CU-2)."""
    out: set[Competency] = set()
    for cat in spec.categories:
        chips: set[str] = set()
        for chip in cat.focus:
            chips |= _stems(chip)
        out.update(c for c in COMPETENCIES_BY_TYPE[cat.category] if _stems(c.value) & chips)
    return out


def _category_of(competency: Competency, kinds: list[InterviewType]) -> InterviewType | None:
    return next((k for k in kinds if competency in COMPETENCIES_BY_TYPE[k]), None)


def _custom_targets(
    config: SessionConfig,
    spec: CustomSessionSpec,
    profile: ResolvedProfile,
    gap: GapAnalysis | None,
) -> list[Competency]:
    """5 or 6 from the session pool: the own questions' competencies first, then those a focus
    chip names, then company weight and the weakest gap scores. Every category gets one."""
    pool = list(session_competencies(config))
    kinds = session_categories(config)
    scores = {c.competency: c.score for c in gap.competency_breakdown} if gap else {}
    own = Counter(c for q in spec.questions for c in q.competencies)
    focus = _focus_matches(spec)

    def rank(c: Competency) -> tuple[int, bool, float, int, int]:
        return (-own[c], c not in focus, -profile.weight(c), scores.get(c, 50), pool.index(c))

    ranked = sorted(pool, key=rank)
    count = min(len(pool), max(COMPETENCIES_BY_DURATION[config.duration_min], len(kinds)))
    chosen = [next(c for c in ranked if c in COMPETENCIES_BY_TYPE[k]) for k in kinds]
    chosen += [c for c in ranked if c not in chosen][: count - len(chosen)]
    chosen.sort(key=ranked.index)
    senior = config.level in (Level.SENIOR, Level.STAFF_PRINCIPAL)
    if senior and Competency.SCOPE_AT_LEVEL in pool and Competency.SCOPE_AT_LEVEL not in chosen:
        # IV-6: senior bars are about scope. It replaces the lowest-ranked target whose
        # category keeps another one.
        for i in range(len(chosen) - 1, -1, -1):
            kind = _category_of(chosen[i], kinds)
            if sum(_category_of(c, kinds) == kind for c in chosen) > 1:
                chosen[i] = Competency.SCOPE_AT_LEVEL
                break
    return chosen


def _quote(text: str) -> str:
    """Candidate text as one quoted, escaped line. Angle brackets are removed, so the text
    cannot close the untrusted block of the prompt."""
    flat = " ".join(text.replace("<", " ").replace(">", " ").split())
    return json.dumps(flat, ensure_ascii=False)


def _neediest(
    spec: CustomSessionSpec,
    counts: Counter[InterviewType | None],
    total: int,
    allowed: list[InterviewType],
) -> InterviewType:
    """The allowed category furthest below its share of `total` questions; ties go to the one
    the candidate listed first."""
    order = [c.category for c in spec.categories]
    share = {c.category: c.share for c in spec.categories}
    return max(allowed, key=lambda k: (share[k] * total - counts[k], -order.index(k)))


def _slots(config: SessionConfig, spec: CustomSessionSpec) -> dict[InterviewType, int]:
    """Planner questions per category. The brief has QUESTIONS_BY_DURATION questions (at least
    the minimum); each open slot goes to the category furthest below its time share."""
    total = QUESTIONS_BY_DURATION[config.duration_min]
    own = len(spec.questions)
    open_slots = max(total - own, MIN_QUESTIONS_BY_DURATION[config.duration_min] - own, 0)
    counts: Counter[InterviewType | None] = Counter(q.category for q in spec.questions)
    out = {c.category: 0 for c in spec.categories}
    for _ in range(open_slots):
        kind = _neediest(spec, counts, total, list(out))
        counts[kind] += 1
        out[kind] += 1
    return out


def _custom_messages(
    config: SessionConfig,
    spec: CustomSessionSpec,
    posting: JobPosting,
    resume: Resume | None,
    profile: ResolvedProfile,
    gap: GapAnalysis | None,
) -> list[Message]:
    """The planner prompt for a Custom session. The candidate's chips and questions go in the
    untrusted block as quoted data."""
    comps = target_competencies(config, profile, gap)
    values = target_values(config, profile)
    kinds = session_categories(config)
    slots = _slots(config, spec)
    wanted = sum(slots.values())
    signals = []
    patterns = []
    if profile.profile is not None:
        for p in profile.profile.values_framework.principles:
            if p.name in values:
                signals.append(f"{p.name}: {'; '.join(p.evidence_signals[:2])}")
        patterns = [
            f"[{q.interview_type.value}] {q.theme}: {q.pattern}"
            for q in profile.profile.question_patterns
            if q.interview_type in kinds
        ][:MAX_PATTERNS]
    categories = []
    for cat in spec.categories:
        mine = [c.value for c in comps if c in COMPETENCIES_BY_TYPE[cat.category]]
        categories.append(
            f"- {cat.category.value}: {round(cat.share * 100)}% of the time, write "
            f"{slots[cat.category]} questions. Competencies: {', '.join(mine)}"
        )
    chips = [
        f"- {cat.category.value}: {', '.join(_quote(f) for f in cat.focus) or '(none)'}"
        for cat in spec.categories
    ]
    own = [f"- [{q.category.value}] {_quote(q.text)}" for q in spec.questions]
    gaps = [f"[{g.severity.value}] {g.summary}" for g in (gap.gaps if gap else [])][:6]
    curveball = config.difficulty == Difficulty.TOUGH
    return [
        load_prompt(Role.PLANNER, PROMPT_CUSTOM).message("system"),
        load_prompt(Role.PLANNER, PROMPT_CUSTOM_INPUT).message(
            "user",
            question_count=min(max(wanted + DRAFT_SPARE, DRAFT_MIN), DRAFT_MAX),
            planned=wanted,
            categories="\n".join(categories),
            level=config.level.value,
            seniority_bar=seniority_bar(config, posting, profile),
            difficulty=config.difficulty.value,
            mode=config.mode.value,
            duration=config.duration_min,
            company=profile.company_name if not profile.generic else "generic mode (no profile)",
            values="\n".join(signals) or "(none: generic mode, leave values empty)",
            patterns="\n".join(patterns) or "(none)",
            sample_questions="\n".join(sample_questions(config, profile, comps)) or "(none)",
            curveball="Write one curveball." if curveball else "Set curveball to null.",
            focus="\n".join(chips),
            own_questions="\n".join(own) or "(none)",
            probe_areas="\n".join(probe_areas(gap)) or "(none)",
            gaps="\n".join(gaps) or "(none)",
            job=posting_text(posting),
            resume=resume_text(resume) if resume else "(no resume)",
        ),
    ]


def _own_questions(spec: CustomSessionSpec) -> list[BriefQuestion]:
    """The candidate's questions as written (trimmed only), with ids c1, c2, ... (CU-4)."""
    return [
        BriefQuestion(
            id=f"c{i}",
            text=q.text.strip(),
            competencies=list(q.competencies),
            priority=i,
            source=QuestionSource.CANDIDATE,
            category=q.category,
            must_ask=q.must_ask,
            verbatim=q.verbatim,
        )
        for i, q in enumerate(spec.questions, start=1)
    ]


def _custom_questions(
    draft: BriefDraft,
    config: SessionConfig,
    spec: CustomSessionSpec,
    comps: list[Competency],
    values: list[str],
    flags: list[str],
) -> tuple[list[BriefQuestion], list[Competency]]:
    """The own questions plus planner questions spread over the categories by time share.
    Returns the questions in asking order and the target competencies."""
    kinds = session_categories(config)
    own = _own_questions(spec)
    seen_ids = {q.id for q in own}
    seen_text = {" ".join(q.text.lower().split()) for q in own}
    buckets: dict[InterviewType, list[BriefQuestion]] = {k: [] for k in kinds}
    floating: list[BriefQuestion] = []
    for q in sorted(draft.questions, key=lambda q: q.priority):
        text = q.text.strip()[:MAX_TEXT]
        key = " ".join(text.lower().split())
        if key in seen_text:
            flags.append(f"duplicate_question: {q.id}")
            continue
        seen_text.add(key)
        qid = q.id if _ID.match(q.id) and q.id not in seen_ids else f"p{len(seen_ids) + 1}"
        while qid in seen_ids:
            qid = f"{qid}x"
        seen_ids.add(qid)
        kind = q.category if q.category in kinds else None
        if kind is None:
            votes = Counter(k for c in q.competencies if (k := _category_of(c, kinds)))
            if votes:
                kind = max(votes, key=lambda k: (votes[k], -kinds.index(k)))
                flags.append(f"category_assigned: {qid}")
        cleaned = BriefQuestion(
            id=qid,
            text=text,
            competencies=list(dict.fromkeys(q.competencies)),  # fitted to the final category
            values=[v for v in dict.fromkeys(q.values) if v in values],
            priority=q.priority,
            probe_hints=[h.strip()[:MAX_HINT] for h in q.probe_hints if h.strip()][:MAX_HINTS],
            category=kind,
        )
        if kind is None:
            floating.append(cleaned)
        else:
            buckets[kind].append(cleaned)

    total = QUESTIONS_BY_DURATION[config.duration_min]
    open_slots = sum(_slots(config, spec).values())
    counts: Counter[InterviewType | None] = Counter(q.category for q in own)
    picked: list[BriefQuestion] = []
    for _ in range(open_slots):
        ready = [k for k in kinds if buckets[k] or floating]
        if not ready:
            break
        kind = _neediest(spec, counts, total, ready)
        if buckets[kind]:
            chosen = buckets[kind].pop(0)
        else:
            # The model gave no usable category: the least covered category takes it.
            chosen = floating.pop(0).model_copy(update={"category": kind})
            flags.append(f"category_assigned: {chosen.id}")
        counts[kind] += 1
        picked.append(_fit_competencies(chosen, kind, comps, [*own, *picked], flags))

    questions = _custom_order([*own, *picked], spec)
    targets = list(comps)
    _cover_custom(questions, targets, flags)
    return questions, targets


def _fit_competencies(
    q: BriefQuestion,
    kind: InterviewType,
    comps: list[Competency],
    done: list[BriefQuestion],
    flags: list[str],
) -> BriefQuestion:
    """Keep the competencies of the question's category; else give it the least covered target
    competency of that category."""
    pool = COMPETENCIES_BY_TYPE[kind]
    kept = [c for c in q.competencies if c in pool][:2]
    if not kept:
        options = [c for c in comps if c in pool] or list(pool)
        kept = [_least_covered(done, options)]
        flags.append(f"competency_reassigned: {q.id}")
    return q.model_copy(update={"competencies": kept})


def _custom_order(questions: list[BriefQuestion], spec: CustomSessionSpec) -> list[BriefQuestion]:
    """Asking order and priorities: categories in the candidate's order; within one, own and
    planner questions alternate (own must-ask ones first among the own). Must-ask questions get
    priorities 1..m, the rest follow in asking order."""
    ordered: list[BriefQuestion] = []
    for cat in spec.categories:
        mine = [q for q in questions if q.category == cat.category]
        own = sorted(
            (q for q in mine if q.source == QuestionSource.CANDIDATE),
            key=lambda q: (not q.must_ask, q.priority),
        )
        planner = sorted(
            (q for q in mine if q.source == QuestionSource.PLANNER), key=lambda q: q.priority
        )
        for i in range(max(len(own), len(planner))):
            ordered += own[i : i + 1] + planner[i : i + 1]
    first = [q for q in ordered if q.must_ask]
    rest = [q for q in ordered if not q.must_ask]
    rank = {q.id: i for i, q in enumerate([*first, *rest], start=1)}
    return [q.model_copy(update={"priority": rank[q.id]}) for q in ordered]


def _cover_custom(
    questions: list[BriefQuestion], targets: list[Competency], flags: list[str]
) -> None:
    """Make every target competency appear in a question (both lists in place).

    Own questions keep the competencies the candidate's check gave them. A missing target is
    added to a planner question of its category; with none, it leaves the targets while more
    than the minimum remain."""
    for comp in list(targets):
        if any(comp in q.competencies for q in questions):
            continue
        hosts = [
            i
            for i, q in enumerate(questions)
            if q.source == QuestionSource.PLANNER
            and q.category is not None
            and comp in COMPETENCIES_BY_TYPE[q.category]
        ]
        if hosts:
            i = min(hosts, key=lambda i: len(questions[i].competencies))
            questions[i] = questions[i].model_copy(
                update={"competencies": [*questions[i].competencies, comp]}
            )
        elif len(targets) > FULL_MIN_COMPETENCIES:
            targets.remove(comp)
            flags.append(f"target_dropped: {comp.value}")
        else:
            flags.append(f"target_uncovered: {comp.value}")
