"""CU-5: check one own question or free-text focus chip before the session.

Order:
1. Code checks, no model call: empty, too long, and text that plainly tries to instruct the
   interviewer (`looks_like_instructions`). These are refused with `instructions` (or
   `not_a_question` for empty and too long text).
2. The extractor role returns a CustomQuestionCheck. The candidate text goes only into the
   `<untrusted_input>` data block of the user message, never into the system prompt.
3. Code keeps only competencies of the category (the caller's category when given), at most 3.

The near-duplicate flag compares normalized text with difflib (ratio >= 0.85). It needs no model.
The model's reason is untrusted: it is cut to 200 characters and dropped when it looks like
instructions. The candidate sees a fixed sentence per refusal, then that reason.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    Competency,
    CustomQuestionCheck,
    InterviewType,
    QuestionRefusal,
)
from strong_core.schemas.custom import (
    CUSTOM_FOCUS_MAX_LEN,
    CUSTOM_QUESTION_MAX_COMPETENCIES,
    CUSTOM_QUESTION_MAX_LEN,
)

Kind = Literal["question", "focus"]

DUPLICATE_RATIO: Final = 0.85
MAX_REASON: Final = 200

MAX_LEN: Final[dict[Kind, int]] = {
    "question": CUSTOM_QUESTION_MAX_LEN,
    "focus": CUSTOM_FOCUS_MAX_LEN,
}

# The fixed sentence the candidate sees first, by refusal and kind.
REFUSAL_MESSAGES: Final[dict[QuestionRefusal, dict[Kind, str]]] = {
    QuestionRefusal.NOT_A_QUESTION: {
        "question": "This does not look like an interview question.",
        "focus": "This does not look like an interview topic.",
    },
    QuestionRefusal.INAPPROPRIATE: {
        "question": "This question can't be used in a practice interview.",
        "focus": "This topic can't be used in a practice interview.",
    },
    QuestionRefusal.INSTRUCTIONS: {
        "question": "Questions can't give instructions to the interviewer.",
        "focus": "Focus topics can't give instructions to the interviewer.",
    },
}
EMPTY_REASON: Final[dict[Kind, str]] = {
    "question": "Type a question first.",
    "focus": "Type a topic first.",
}
TOO_LONG_REASON: Final = "Keep it under {limit} characters."

_KIND_NAMES: Final[dict[Kind, str]] = {"question": "question", "focus": "focus topic"}
_KIND_RULES: Final[dict[Kind, str]] = {
    "question": (
        "The text should be one question an interviewer could ask a candidate in a job "
        'interview, for example "Tell me about a time you disagreed with your manager" or '
        '"How would you design a rate limiter?". A short request that works as an interview '
        'prompt ("Walk me through your last project") counts as a question.'
    ),
    "focus": (
        "The text should be a short topic for an interviewer to focus on, for example "
        '"conflict with stakeholders", "Kubernetes" or "pricing strategy". is_question means '
        "a fair interview topic here."
    ),
}

_WORDS = r"[^.\n]{0,60}"
INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget|override|bypass)\s+(all\s+|any\s+)?(the\s+)?(previous|prior"
        r"|above|earlier|your|these|those|my|system|all)\b[^.\n]{0,40}\b(instructions?|prompts?"
        r"|rules|guidelines|directions|directives|persona|role)\b",
        r"\b(ignore|disregard|forget)\s+(all\s+)?(instructions|prompts?)\b",
        r"\b(system|developer)\s+(prompt|message|instructions?)\b",
        r"\byour\s+(instructions|prompt)\b",
        r"\byou\s+are\s+(now|no\s+longer)\b",
        r"\bfrom\s+now\s+on\b",
        r"\bnew\s+instructions?\b",
        r"^\s*(system|assistant|developer|user)\s*:",
        r"\bdo\s+not\s+(follow|obey)\b",
        r"\bas\s+an?\s+(ai|llm|language\s+model)\b",
        r"\b(act|behave|respond|speak|talk)\s+(as|like)\s+(an?\s+|my\s+|the\s+)?"
        r"(ai|assistant|chatbot|bot|pirate|friend|character)\b",
        r"\b(pretend|imagine)\s+(to\s+be|you\s+are|you're|that\s+you)\b",
        r"\brole[\s-]?play\b",
        r"\bplay\s+the\s+(role|part)\s+of\b",
        rf"\b(reveal|print|show|repeat|output|leak)\b{_WORDS}\b(system\s+prompt|instructions"
        r"|prompt)\b",
        rf"\b(give|rate|score|grade|mark)\s+(me|the\s+candidate|this\s+candidate)\b{_WORDS}"
        r"\b(strong\s+hire|hire|perfect|top|best|full\s+marks|10\s*/\s*10|[1-4]\s*/\s*4)\b",
        r"\b(prompt\s+injection|jailbreak)\b",
        r"^\s*(please\s+)?(do\s+not|don't|never)\s+(ask|probe|interrupt|follow[\s-]?up|score)\b",
        r"\b(end|stop|finish|skip)\s+(the|this)\s+(interview|session)\b",
        r"<\|[^|>]{0,40}\|>|\[/?INST\]|<<\s*/?SYS\s*>>|</?\s*untrusted_input\s*>",
        r"</?\s*(system|assistant|user|instructions?)\s*>",
    )
)

_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKERS = re.compile(r"</?\s*untrusted_input\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class CheckResult:
    accepted: bool
    refusal: QuestionRefusal | None
    reason: str
    category: InterviewType | None
    competencies: tuple[Competency, ...]
    model: str | None = None
    prompt_refs: tuple[str, ...] = ()


def clean_text(text: str) -> str:
    """NFKC, no invisible or control characters, single spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", text))
    return " ".join(text.split())


def looks_like_instructions(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


def normalize_for_duplicates(text: str) -> str:
    text = clean_text(text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def find_duplicate(text: str, existing: Sequence[str]) -> int | None:
    """Index of the first entry of `existing` that is a near-duplicate of `text` (CU-5)."""
    mine = normalize_for_duplicates(text)
    if not mine:
        return None
    for i, other in enumerate(existing):
        theirs = normalize_for_duplicates(other)
        if theirs and difflib.SequenceMatcher(None, mine, theirs).ratio() >= DUPLICATE_RATIO:
            return i
    return None


def refusal_reason(refusal: QuestionRefusal, kind: Kind, detail: str = "") -> str:
    first = REFUSAL_MESSAGES[refusal][kind]
    return f"{first} {detail}".strip() if detail else first


def _clean_reason(reason: str) -> str:
    text = clean_text(reason)[:MAX_REASON].strip()
    if not text or looks_like_instructions(text):
        return ""
    return text if text[-1] in ".!?" else text + "."


def _refused(
    refusal: QuestionRefusal,
    kind: Kind,
    detail: str = "",
    model: str | None = None,
    prompt_refs: tuple[str, ...] = (),
) -> CheckResult:
    return CheckResult(
        accepted=False,
        refusal=refusal,
        reason=refusal_reason(refusal, kind, detail),
        category=None,
        competencies=(),
        model=model,
        prompt_refs=prompt_refs,
    )


def code_check(text: str, kind: Kind) -> CheckResult | None:
    """The refusal from the cheap code checks, or None when the text goes to the model."""
    if not text:
        return _refused(QuestionRefusal.NOT_A_QUESTION, kind, EMPTY_REASON[kind])
    limit = MAX_LEN[kind]
    if len(text) > limit:
        return _refused(QuestionRefusal.NOT_A_QUESTION, kind, TOO_LONG_REASON.format(limit=limit))
    if looks_like_instructions(text):
        return _refused(QuestionRefusal.INSTRUCTIONS, kind)
    return None


def _competency_list() -> str:
    lines = []
    for itype in STANDARD_INTERVIEW_TYPES:
        names = ", ".join(c.value for c in COMPETENCIES_BY_TYPE[itype])
        lines.append(f"  - {itype.value}: {names}")
    return "\n".join(lines)


def build_messages(text: str, kind: Kind, category: InterviewType | None) -> list[Message]:
    hint = (
        f"The candidate filed it under {category.value}; keep that unless it clearly does not fit."
        if category is not None
        else "Choose one of:"
    )
    if category is not None:
        hint += " The kinds are:"
    safe = _MARKERS.sub(" ", text)
    return [
        load_prompt(Role.EXTRACTOR, "custom_question_check").message(
            "system",
            kind_name=_KIND_NAMES[kind],
            kind_rules=_KIND_RULES[kind],
            category_hint=hint,
            competencies=_competency_list(),
        ),
        load_prompt(Role.EXTRACTOR, "check_input").message("user", text=safe),
    ]


def pick_competencies(
    category: InterviewType, tagged: Sequence[Competency]
) -> tuple[Competency, ...]:
    """The tagged competencies that belong to `category`, at most 3. When none fit, the first
    competency of the category, so an accepted question is always tagged."""
    allowed = COMPETENCIES_BY_TYPE[category]
    kept = [c for c in dict.fromkeys(tagged) if c in allowed][:CUSTOM_QUESTION_MAX_COMPETENCIES]
    return tuple(kept) if kept else (allowed[0],)


async def check_question(
    gateway: ModelGateway, text: str, kind: Kind, category: InterviewType | None
) -> CheckResult:
    """Run the CU-5 check. Raises when the model call fails (the API answers 503)."""
    clean = clean_text(text)
    refused = code_check(clean, kind)
    if refused is not None:
        return refused
    done = await gateway.complete(
        Role.EXTRACTOR, build_messages(clean, kind, category), output_type=CustomQuestionCheck
    )
    check = done.output
    if not check.is_question:
        refusal = check.refusal or QuestionRefusal.NOT_A_QUESTION
        detail = _clean_reason(check.reason)
        return _refused(refusal, kind, detail, done.model, done.prompt_refs)
    chosen = category or check.category or InterviewType.BEHAVIORAL
    return CheckResult(
        accepted=True,
        refusal=None,
        reason="",
        category=chosen,
        competencies=pick_competencies(chosen, check.competencies),
        model=done.model,
        prompt_refs=done.prompt_refs,
    )
