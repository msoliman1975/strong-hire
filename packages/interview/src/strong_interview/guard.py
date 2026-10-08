"""Output guard for the interviewer's spoken reply. It works together with the turn prompt.

The prompt tells the model to speak only the words to say, never to give feedback, and to state
the real session length. Models still break these rules sometimes, so every reply passes this
deterministic check before anyone hears it. Rules:

- meta: the reply describes the interviewer's reasoning or instructions instead of speaking
  ("The candidate asked ...", "I should say ...", "The facts I have ..."). The sentence is removed.
- feedback: evaluative words about the candidate's answers ("useful compromise", "helpful detail",
  "quite detailed", "thoughtful answers", "that's clear"). The clause is removed; a sentence that
  opened with "Thanks" keeps "Thanks.". Questions and requests ("Tell me about a good example")
  are kept; only an evaluative clause in front of them is removed.
- duration: the agenda or the greeting names a session length that is not the real one. The
  number is replaced with the real length.
- repeat: a question that is the same, or nearly the same, as a question in the interviewer's
  previous turn. The redo move may repeat. The reply is not usable then.

The rules are kept narrow on purpose, so normal questions pass unchanged. When nothing usable is
left, the Interviewer asks the model once more with a stricter instruction, and then falls back
to a fixed line for the move (`fallback_line`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from strong_interview.controller import MoveKind

MIN_WORDS = 2  # a reply with fewer words left is not usable
REPEAT_RATIO = 0.8  # word-sequence similarity at which a question counts as a repeat

_META = re.compile(
    r"""
    \bthe\ (candidate|interviewee)('s)?\ (asked|asks|is\ asking|said|says|mentioned|wants
        |wanted|answered|gave|described|explained|didn't|did\ not|question|answer|response
        |reply)\b
    | ^\s*(the\ )?(candidate|interviewee)\ (asked|asks|said|says|wants|answered)\b
    | \bthe\ facts\ (I|we|you\ gave|provided|given|listed|available|don't|do\ not|say|cover
        |mention)\b
    | \b(my|the\ provided|the\ given|the\ listed|the\ available)\ facts\b
    | \bfacts\ (I|we)\ (have|was\ given|were\ given|got)\b
    | \bI\ (should|need\ to|must|have\ to|will\ now|'ll\ now)\ (say|ask|respond|reply|answer
        |acknowledge|probe|tell\ (him|her|them)|stay|keep\ (it|this)|not\ (invent|make|say|give))\b
    | \bso\ I('ll|\ will|\ should)?\ (say|respond|reply)\b
    | \bmy\ (next\ )?move\b
    | \bthe\ move\ (here\ )?(is|should\ be)\ (to\ )?(ask|probe|greet|answer|wrap|invite|give)\b
    | \b(small_talk|invite_questions|answer_question|wrap_up)\b
    | \b(system|my)\ prompt\b
    | \bmy\ instructions\b
    | \bthe\ instructions\ (say|tell|are|ask)\b
    | \bthe\ transcript\ (so\ far|shows|says)\b
    | \binterviewer\ brief\b
    | \b(stay|staying|answer|answering)\ in\ persona\b
    | \bpushback\ (is\ )?(on|off)\b
    | \bwhat\ the\ (last\ )?answer\ lacks\b
    | \bprobe\ hints?\b
    | \bas\ an\ (ai|assistant|language\ model)\b
    | \blet\ me\ (draft|craft|formulate|compose)\b
    | \b(here's|here\ is)\ (my|the|a)\ (reply|response|draft)\b
    | ^\s*(note|notes|reasoning|thinking|thought|analysis|plan|draft|meta)\s*:
    """,
    re.IGNORECASE | re.VERBOSE,
)

_GOOD = (
    r"(great|good|excellent|nice|strong|solid|fantastic|wonderful|perfect|impressive|interesting"
    r"|useful|helpful|thoughtful|insightful|clear|detailed|thorough|compelling|fair|reasonable"
    r"|smart|sensible|valid|fascinating|terrific|brilliant)"
)
_ABOUT = (
    r"(answer|answers|point|points|example|examples|start|detail|details|compromise|approach"
    r"|explanation|response|responses|overview|summary|insight|insights|reflection|thinking"
    r"|choice|call|trade-?offs?|story|stories|walkthrough|breakdown|framing|question|context)"
)
_FEEDBACK = re.compile(
    rf"""
    \b{_GOOD}\s+{_ABOUT}\b
    | \b(that's|that\ is|that\ was)\s+(a\s+)?(very\s+|really\s+|quite\s+|so\s+)?
        (clear|helpful|useful|great|good|excellent|interesting|impressive|insightful|fascinating
        |thorough|detailed|smart|fair|reasonable|right|correct|perfect|spot\ on|exactly\ right)\b
    | \b(quite|very|really|so|nicely|super)\s+(detailed|thorough|clear|helpful|insightful
        |comprehensive|structured|articulated|explained)\b
    | \bwell\s+(done|said|put|explained|handled|structured|thought\ out)\b
    | \b(good|great|nice)\s+(job|work)\b
    | \bmakes?\s+(the|it|that|this|things|your)\s+(\S+\s+){{0,2}}clear\b
    | \b(answers?|responses?)\s+(have|has)\s+been\b
    | \byou('ve|\s+have)?\s+(clearly|obviously)\b
    | \bI\s+(really\s+)?(like|love)\s+(that|how|your)\b
    | \bI\s+(really\s+)?appreciate\s+(the|your|how)\s+(detail|clarity|honesty|candou?r|example
        |examples|answer|answers|thoroughness|openness|insight|depth)\b
    # "You covered reconciliation well", "Your answer lays out the options clearly"
    | \b(you|your\s+(answer|response|explanation|example|story))\s+(\w+\s+)?
        (cover|covers|covered|describe|describes|described|explain|explains|explained
        |lay|lays|laid|walk|walks|walked|handle|handles|handled|address|addresses|addressed
        |frame|frames|framed|structure|structures|structured|articulate|articulates|articulated
        |answer|answers|answered|outline|outlines|outlined|break|breaks|broke)\b
        [^.?!]{{0,90}}?\b(well|clearly|nicely|thoroughly|effectively|convincingly|concisely)\b
    # "That beta approach sounds sensible", "That seems reasonable"
    | \b(sounds|seems|looks)\s+(like\s+)?(a\s+)?(very\s+|really\s+|quite\s+)?
        (good|great|sensible|reasonable|solid|smart|fair|strong|valid|nice|right|wise|logical)\b
    # "Kafka is a good tool for that"
    | \b(is|was)\s+a\s+(good|great|solid|sensible|reasonable|fine|strong|smart|nice)\s+
        (tool|choice|option|fit|call|idea|approach|pick|move|decision)\s+for\s+(that|this|it)\b
    # "Thanks for that candid answer"
    | \b(thanks|thank\s+you)\s+for\s+(that|this|the|your)\s+(very\s+|really\s+)?
        (candid|honest|thoughtful|detailed|clear|great|good|helpful|thorough|insightful|open
        |frank|complete|full)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# A sentence that asks for something. Feedback words inside it ("Tell me about a good example")
# are part of the question, not feedback, so only a clause in front of it can be removed.
_REQUEST = re.compile(
    r"^\s*(so\s+|and\s+|but\s+|now\s+|next\s+)?(tell|walk|describe|give|talk|share|explain|take|can"
    r"|could|would|will|how|what|why|when|where|which|who|let's|let\s+us|I'd\s+like|do|did|does"
    r"|is|are|have|has)\b",
    re.IGNORECASE,
)
_LEAD = re.compile(r"^\s*(so|and|but|now)\s+", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSES = re.compile(r",\s+|;\s+|\s+[-\u2013\u2014]\s+")
_WORD = re.compile(r"[a-z0-9']+")
_TAIL_LABEL = re.compile(
    r"(?:^|\n|(?<=[.!?]))\s*(?:interviewer|response|reply|spoken|say|final(?:\s+answer)?)"
    r"\s*:\s*",
    re.IGNORECASE,
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25,
    "twenty five": 25, "thirty": 30, "thirty-five": 35, "thirty five": 35, "forty": 40,
    "forty-five": 45, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}  # fmt: skip
_SAY_NUMBER = {10: "ten", 30: "thirty", 45: "forty-five"}
_MINUTES = re.compile(
    r"\b(?P<num>\d{1,3}|"
    + "|".join(sorted((re.escape(w) for w in _NUMBER_WORDS), key=len, reverse=True))
    + r")(?P<sep>[\s-]+)(?P<unit>minutes?)\b"
    r"|\b(?P<hour>half\s+an\s+hour|an\s+hour|one\s+hour|a\s+full\s+hour)\b",
    re.IGNORECASE,
)
_DURATION_MOVES = (MoveKind.GREET, MoveKind.AGENDA)


@dataclass(frozen=True)
class GuardHit:
    rule: str  # meta, feedback, duration or repeat
    text: str  # the sentence, clause or phrase that broke the rule

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "text": self.text[:300]}


@dataclass(frozen=True)
class GuardResult:
    text: str  # the reply after the fixes; may be empty
    hits: tuple[GuardHit, ...] = field(default=())

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(h.rule for h in self.hits))

    @property
    def usable(self) -> bool:
        """False when too little is left, or the reply repeats the previous question."""
        return len(self.text.split()) >= MIN_WORDS and "repeat" not in self.rules

    def as_dict(self) -> dict[str, Any]:
        return {"rules": list(self.rules), "hits": [h.as_dict() for h in self.hits]}


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("\u2019", "'"))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCES.split(text) if s and s.strip()]


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _split_label(text: str) -> tuple[str, str]:
    """A reply like "Note: ... Response: <words>": returns the part before the last label and
    the words after it. Without a label the first part is empty."""
    matches = list(_TAIL_LABEL.finditer(text))
    if not matches:
        return "", text
    tail = text[matches[-1].end() :].strip().strip('"').strip()
    if not tail:
        return "", text
    return text[: matches[-1].start()].strip(), tail


def _strip_feedback(sentence: str) -> tuple[str, list[str]]:
    """Remove evaluative clauses. Returns the sentence that is left and the removed clauses."""
    if not _FEEDBACK.search(sentence):
        return sentence, []
    end = sentence[-1] if sentence[-1] in ".!?" else "."
    body = sentence[:-1] if sentence[-1] in ".!?" else sentence
    clauses = [c for c in _CLAUSES.split(body) if c.strip()]
    removed: list[str] = []
    kept: list[str] = []
    request_seen = False
    for clause in clauses:
        request = bool(_REQUEST.match(clause)) or (end == "?" and clause is clauses[-1])
        request_seen = request_seen or request
        if not request_seen and _FEEDBACK.search(clause):
            removed.append(clause.strip())
            continue
        kept.append(clause.strip())
    if not removed:
        return sentence, []
    if not kept:
        return "", removed
    joined = ", ".join(kept)
    joined = _LEAD.sub("", joined) if removed and sentence.find(kept[0]) > 0 else joined
    return _capitalize(joined.strip()) + end, removed


def _duration_fixes(
    text: str, duration_min: int, plan_minutes: Iterable[int]
) -> list[tuple[GuardHit, re.Match[str]]]:
    plan = [p for p in plan_minutes if p > 0]
    out = []
    for m in _MINUTES.finditer(text):
        if m["hour"]:
            said = 30 if m["hour"].lower().startswith("half") else 60
        elif m["num"].isdigit():
            said = int(m["num"])
        else:
            said = _NUMBER_WORDS[m["num"].lower()]
        if said == duration_min:
            continue
        if said < duration_min and any(abs(said - p) <= max(2, p * 0.2) for p in plan):
            continue  # a phase of the plan, for example "about twenty minutes of questions"
        out.append((GuardHit("duration", f"{m.group(0)} (session is {duration_min})"), m))
    return out


def _fix_duration(text: str, fixes: list[tuple[GuardHit, re.Match[str]]], duration_min: int) -> str:
    for _, m in reversed(fixes):
        if m["hour"]:
            new = f"{_SAY_NUMBER.get(duration_min, str(duration_min))} minutes"
        elif m["num"].isdigit():
            new = f"{duration_min}{m['sep']}{m['unit']}"
        else:
            word = _SAY_NUMBER.get(duration_min, str(duration_min))
            new = f"{_capitalize(word) if m['num'][0].isupper() else word}{m['sep']}{m['unit']}"
        text = text[: m.start()] + new + text[m.end() :]
    return text


def _questions(text: str) -> list[list[str]]:
    return [_words(s) for s in _sentences(text) if s.endswith("?") and len(_words(s)) >= 3]


def is_repeat(reply: str, previous: str | None) -> bool:
    """True when a question in `reply` is (nearly) word for word a question in `previous`."""
    if not previous:
        return False
    before = _questions(previous)
    for asked in _questions(reply):
        for old in before:
            if SequenceMatcher(None, asked, old, autojunk=False).ratio() >= REPEAT_RATIO:
                return True
    return False


def guard_reply(
    text: str,
    move: MoveKind,
    *,
    duration_min: int,
    plan_minutes: Iterable[int] = (),
    previous: str | None = None,
) -> GuardResult:
    """Check and fix one reply. `previous` is the interviewer's previous turn, if any."""
    hits: list[GuardHit] = []
    head, text = _split_label(text.replace("\u2019", "'").strip())
    if head:
        hits.append(GuardHit("meta", head))
    kept: list[str] = []
    for sentence in _sentences(text):
        if _META.search(sentence):
            hits.append(GuardHit("meta", sentence))
            continue
        if move != MoveKind.HINT:
            sentence, removed = _strip_feedback(sentence)
            hits += [GuardHit("feedback", clause) for clause in removed]
        if sentence:
            kept.append(sentence)
    result = " ".join(kept).strip()
    if move in _DURATION_MOVES:
        fixes = _duration_fixes(result, duration_min, plan_minutes)
        if fixes:
            hits += [hit for hit, _ in fixes]
            result = _fix_duration(result, fixes, duration_min)
    if move != MoveKind.REDO and is_repeat(result, previous):
        hits.append(GuardHit("repeat", result))
    return GuardResult(result, tuple(hits))


def _say_minutes(minutes: int) -> str:
    return _SAY_NUMBER.get(minutes, str(minutes))


def fallback_line(
    move: MoveKind,
    *,
    name: str,
    duration_min: int,
    mini: bool,
    question: str | None,
    closing: bool = False,
    open_question: bool = False,
) -> str:
    """A fixed, safe line for the move, used when the model gave nothing usable twice.

    `closing`: the last answer before the wrap-up, so it does not invite more questions.
    `open_question`: the wrap-up after a question there was no time to answer.
    """
    if move == MoveKind.GREET:
        return f"Hello, I'm {name}, and I'll be your interviewer today. Thanks for your time."
    if move == MoveKind.SMALL_TALK:
        return "Before we start, how has your day been so far?"
    if move == MoveKind.AGENDA:
        if mini:
            return (
                f"This is a short {_say_minutes(duration_min)}-minute interview. I'll ask you a "
                "few questions about your experience, and then we'll wrap up."
            )
        return (
            f"We have about {_say_minutes(duration_min)} minutes. I'll ask you about your "
            "experience, with some follow-up questions, and we'll keep a few minutes at the end "
            "for your questions."
        )
    if move in (MoveKind.ASK, MoveKind.CURVEBALL) and question:
        return question
    if move == MoveKind.REDO and question:
        return f"Sure, take another try. {question}"
    if move == MoveKind.PROBE:
        return "Could you walk me through one specific part of that in more detail?"
    if move == MoveKind.HINT:
        return "Take a moment, and think of one specific example you could walk me through."
    if move == MoveKind.INVITE_QUESTIONS:
        return "That covers my questions. What questions do you have for me?"
    if move == MoveKind.ANSWER_QUESTION:
        if closing:
            return "I'm afraid I don't know that detail."
        return "I'm afraid I don't know that detail. Is there anything else you'd like to ask?"
    if move == MoveKind.WRAP_UP and open_question:
        return (
            "Thanks for your question; the recruiter can follow up on it. Thank you for your "
            "time today. The team will be in touch about next steps. Goodbye."
        )
    if move == MoveKind.WRAP_UP:
        return "Thank you for your time today. The team will be in touch about next steps. Goodbye."
    return "Let's continue."
