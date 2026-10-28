"""The coach's turn logic (CO-2 to CO-5), without HTTP, so the text API and the voice agent's
internal endpoint run the same code.

One candidate turn:

1. Conduct (IV-12 rules): the fixed abuse list (`strong_interview.conduct.screen_turn`), then a
   coach-role AnswerCheck. A turn outside the session gets a fixed warning line and changes
   nothing; the third such turn ends the session. The lines are fixed text, never model output.
2. What to ask for next (CO-4) is picked in code, from the story's state, in this order:
   one concrete example (context), stakes, the candidate's own role, a measurable result,
   trade-offs, reflection. The model is told to ask about that one thing.
3. The coach role returns a CoachReply. Each part update is kept only when every quote is found,
   word for word, in what the candidate typed or said on this story (CO-3), and every number in
   the part's text is in its quotes. The rest are dropped and logged. `missing` is recomputed
   from the story, not taken from the model.
4. The reply's message keeps one question at most (CO-4): anything after the first "?" is cut.
5. The style (CO-5) is a section of the system prompt (`prompts/coach/style_<style>`), and the
   reply is held to it: a direct reply is the question alone; a gentle acknowledgement that
   grades the story ("a meaningful outcome") becomes "Thank you.".

IV-3 pressing (ask once more from another angle before moving on) is in the turn prompt: the
model sees the conversation and knows whether the candidate already said no twice.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach.schemas import AskFor
from strong_core.db.models import CoachSession, CoachTurn
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Message, ModelGateway, Role, usage_context
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    AnswerCheck,
    AnswerConduct,
    CoachReply,
    CoachSessionStatus,
    CoachSpeaker,
    CoachStyle,
    Competency,
    StoryPart,
    StoryPartUpdate,
)
from strong_interview.conduct import MAX_CONDUCT_WARNINGS, screen_turn

log = logging.getLogger(__name__)

PARTS = tuple(StoryPart)
MIN_QUOTE_WORDS = 3  # a shorter quote ("the team") would match almost any turn
TRANSCRIPT_TURNS = 20  # the most recent turns the model sees

# CO-4: what the coach asks for, as fixed lines. The opener and the fallback (when the model
# call fails) use them; the model writes its own question for the same thing.
ASK_LINES: dict[AskFor, str] = {
    AskFor.CONCRETE_EXAMPLE: "Tell me about one specific time at work. What was going on?",
    AskFor.STAKES: "Why did it matter? What was at stake?",
    AskFor.OWN_ROLE: "What did you do yourself?",
    AskFor.MEASURABLE_RESULT: "What changed in the end? A number helps, if you have one.",
    AskFor.TRADEOFF_REASONING: "What options did you weigh, and why did you pick the one you did?",
    AskFor.REFLECTION: "Looking back, what did you learn, or what would you do differently?",
    AskFor.NOTHING: "All five parts are there. Do you want to sharpen anything, or are you done?",
}
# What the model is told to ask for, one line each.
_ASK_FOR_MODEL: dict[AskFor, str] = {
    AskFor.CONCRETE_EXAMPLE: "one concrete example: a specific time, where they worked, what "
    "was going on (context)",
    AskFor.STAKES: "why it mattered and what could go wrong (stakes)",
    AskFor.OWN_ROLE: "the candidate's own role: what they did themselves, not the team (action)",
    AskFor.MEASURABLE_RESULT: "a measurable result: what changed, with a number; if they have "
    "none, a rough figure, a before and after, or how they knew it worked (result)",
    AskFor.TRADEOFF_REASONING: "the trade-offs: which options they weighed and why they chose "
    "theirs",
    AskFor.REFLECTION: "what they learned or would do differently (reflection)",
    AskFor.NOTHING: "nothing is missing; ask whether they want to sharpen a part or finish",
}

_OPEN_NEW = "Let's build one story together, from your own work."
_OPEN_SKILL = "Let's build one story that shows {skill}, from your own work."
_OPEN_EXISTING = 'Let\'s work on "{title}".'

# IV-12 for the coach: fixed lines. The first line of each warning marks the turn as a strike.
_FIRST: dict[AnswerConduct, str] = {
    AnswerConduct.OFF_SCOPE: "Let's keep this session on your story.",
    AnswerConduct.INAPPROPRIATE: "Let's keep our conversation respectful.",
}
_LAST = "This is my second reminder. If it happens again, I will end the session."
_CLOSE: dict[AnswerConduct, str] = {
    AnswerConduct.OFF_SCOPE: (
        "I'm going to end the session here, because we kept moving away from your story. "
        "Your story is saved, and you can start a new session when you're ready."
    ),
    AnswerConduct.INAPPROPRIATE: (
        "I'm going to end the session here, because the conversation did not stay respectful. "
        "Your story is saved, and you can start a new session when you're ready."
    ),
}
_STRIKE_PREFIXES = (*_FIRST.values(), *_CLOSE.values())

_WE = re.compile(r"\b(we|our|us|the team)\b", re.IGNORECASE)
_I = re.compile(r"\b(i|i'm|i'd|i've|me|my|myself)\b", re.IGNORECASE)
# Curly quotes and dashes, as speech-to-text and phones write them, to plain ones.
_TYPOGRAPHIC = str.maketrans(
    {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"}
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# A result is measurable with digits or with a number in words ("five percent", "not one
# payment failed", "doubled"); IV-3 asks for a measure, not for digits.
_MEASURE = re.compile(
    r"\d|\b(zero|none|not (one|a single)|no \w+ (failed|lost|dropped)|two|three|four|five"
    r"|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand"
    r"|million|billion|dozen|half|twice|double[ds]?|triple[ds]?|percent|per cent)\b",
    re.IGNORECASE,
)
# CO-5: words that grade the story. The gentle coach never uses them in its acknowledgement.
_PRAISE = re.compile(
    r"\b(good|great|clear|clearly|strong|solid|real|meaningful|helpful|useful|careful"
    r"|thoughtful|impressive|excellent|nice|important|valuable|perfect|smart|wise|brilliant"
    r"|fantastic|amazing|wonderful|sounds like|well done)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!])\s+")
GENTLE_LEAD = "Thank you."
_TRADEOFF = re.compile(
    r"\b(instead|rather than|trade-?offs?|options?|alternatives?|chose|choose|decided|weigh"
    r"\w*|versus|vs\.?|downside|at the cost of)\b",
    re.IGNORECASE,
)


# --- story state -----------------------------------------------------------------------------


def part_text(story: StoryRow, part: StoryPart) -> str | None:
    value: str | None = getattr(story, part.value)
    return value if value and value.strip() else None


def missing_parts(story: StoryRow) -> list[StoryPart]:
    return [p for p in PARTS if part_text(story, p) is None]


def asks(story: StoryRow) -> list[AskFor]:
    """CO-4: everything the story still lacks, in the order the coach asks for it.

    A missing part comes first. Then the IV-3 checks on filled parts: an action told only as
    "we", a result with no number, an action and reflection that name no choice."""
    out: list[AskFor] = []
    context, stakes = part_text(story, StoryPart.CONTEXT), part_text(story, StoryPart.STAKES)
    action, result = part_text(story, StoryPart.ACTION), part_text(story, StoryPart.RESULT)
    reflection = part_text(story, StoryPart.REFLECTION)
    if context is None:
        out.append(AskFor.CONCRETE_EXAMPLE)
    if stakes is None:
        out.append(AskFor.STAKES)
    if action is None or (_WE.search(action) and not _I.search(action)):
        out.append(AskFor.OWN_ROLE)
    if result is None or not _MEASURE.search(result):
        out.append(AskFor.MEASURABLE_RESULT)
    if action is not None and not _TRADEOFF.search(f"{action} {reflection or ''}"):
        out.append(AskFor.TRADEOFF_REASONING)
    if reflection is None:
        out.append(AskFor.REFLECTION)
    return out or [AskFor.NOTHING]


def merge_skills(current: Sequence[str], new: Sequence[Competency]) -> list[str]:
    out = [Competency(s).value for s in current]
    out.extend(s.value for s in new if s.value not in out)
    return out


def skill_label(skill: Competency) -> str:
    return skill.value.replace("_", " ")


def opener(story: StoryRow, *, is_new: bool, target_skill: Competency | None) -> str:
    """The coach's first line: fixed text, no model call."""
    if not is_new:
        lead = _OPEN_EXISTING.format(title=story.title)
    elif target_skill is not None:
        lead = _OPEN_SKILL.format(skill=skill_label(target_skill))
    else:
        lead = _OPEN_NEW
    return f"{lead} {ASK_LINES[asks(story)[0]]}"


# --- CO-3: quotes back every part ------------------------------------------------------------


def _normal(text: str) -> str:
    text = text.translate(_TYPOGRAPHIC)
    return " ".join(re.sub(r"[^\w%$'.,-]+", " ", text.lower()).split())


def _clean_quote(quote: str) -> str:
    return _normal(quote).strip(" .,'-\"")


def quote_found(quote: str, said: str) -> bool:
    """The quote is the candidate's words: at least MIN_QUOTE_WORDS words, found in `said`
    (case, spacing and punctuation between words are ignored)."""
    q = _clean_quote(quote)
    return len(q.split()) >= MIN_QUOTE_WORDS and q in said


def backed(update: StoryPartUpdate, said: str) -> str | None:
    """None when every quote is the candidate's and every number in the text is quoted, else
    why the update is dropped."""
    for quote in update.quotes:
        if not quote_found(quote, said):
            return f"quote not found: {quote[:80]!r}"
    quoted = " ".join(_normal(q) for q in update.quotes)
    for number in _NUMBER.findall(update.text):
        if number not in quoted:
            return f"number not in the quotes: {number}"
    return None


def one_question(message: str) -> str:
    """CO-4: one question per reply. Cut what follows the first question mark."""
    head, mark, _ = message.partition("?")
    return f"{head}{mark}".strip() if mark else message.strip()


def styled(message: str, style: CoachStyle) -> str:
    """CO-5: hold a one-question reply to its style guide.

    Direct: the question alone, with no acknowledgement before it. Gentle: an acknowledgement
    that grades the story ("a meaningful outcome") becomes "Thank you.". A reply with no
    question (the wrap-up) is left as it is."""
    if not message.endswith("?"):
        return message
    *lead, question = _SENTENCE_END.split(message)
    if not lead:
        return message
    if style == CoachStyle.DIRECT:
        return question
    if _PRAISE.search(" ".join(lead)):
        return f"{GENTLE_LEAD} {question}"
    return message


# --- conduct (IV-12 rules) -------------------------------------------------------------------


def strikes(turns: Sequence[CoachTurn]) -> int:
    return sum(
        1 for t in turns if t.speaker == CoachSpeaker.COACH and t.text.startswith(_STRIKE_PREFIXES)
    )


def warning(conduct: AnswerConduct, *, last: bool, ask: AskFor) -> str:
    parts = [_FIRST[conduct]]
    if last:
        parts.append(_LAST)
    parts.append(f"Back to your story: {ASK_LINES[ask]}")
    return " ".join(parts)


# --- the turn --------------------------------------------------------------------------------


@dataclass
class TurnResult:
    reply: CoachReply
    ask: AskFor
    conduct: AnswerConduct = AnswerConduct.OK
    ended: bool = False
    dropped: list[str] = field(default_factory=list)  # why part updates were dropped
    turns: list[CoachTurn] = field(default_factory=list)  # the two turns this call added


def _render_story(story: StoryRow) -> str:
    lines = [f"Title: {story.title}"]
    for part in PARTS:
        lines.append(f"{part.value}: {part_text(story, part) or '(empty)'}")
    return "\n".join(lines)


def _render_transcript(turns: Sequence[CoachTurn]) -> str:
    recent = list(turns)[-TRANSCRIPT_TURNS:]
    if not recent:
        return "(nothing yet)"
    return "\n".join(f"{t.speaker.value}: {t.text}" for t in recent)


def turn_messages(
    session: CoachSession,
    story: StoryRow,
    turns: Sequence[CoachTurn],
    answer: str,
    order: Sequence[AskFor],
) -> list[Message]:
    """System and user messages for one coach turn. The candidate's text is data only."""
    style = load_prompt(Role.COACH, f"style_{session.style.value}").render()
    target = ", ".join(skill_label(Competency(s)) for s in story.skills) or "none chosen"
    return [
        load_prompt(Role.COACH, "turn").message(
            "system", style=style, skills=", ".join(c.value for c in Competency)
        ),
        load_prompt(Role.COACH, "turn_input").message(
            "user",
            story=_render_story(story),
            target_skill=target,
            transcript=_render_transcript(turns),
            ask=_ASK_FOR_MODEL[order[0]],
            then=_ASK_FOR_MODEL[order[1]] if len(order) > 1 else "nothing else",
            answer=answer,
        ),
    ]


async def check_turn(gateway: ModelGateway, asked: str, answer: str) -> AnswerConduct:
    """IV-12 for the coach: the fixed abuse list, then the model check. Ok when the call fails."""
    screened = screen_turn(answer)
    if screened is not None:
        return screened
    messages = [
        load_prompt(Role.COACH, "check_turn").message("system"),
        load_prompt(Role.COACH, "check_turn_input").message("user", asked=asked, answer=answer),
    ]
    try:
        done = await gateway.complete(Role.COACH, messages, output_type=AnswerCheck)
    except Exception:
        log.warning("coach turn check failed; the turn counts as ok", exc_info=True)
        return AnswerConduct.OK
    return done.output.conduct


async def candidate_words(db: AsyncSession, session: CoachSession) -> str:
    """Everything the candidate typed or said on this story (or in this session, before the
    story exists), normalized for quote matching."""
    query = select(CoachTurn.text).join(CoachSession, CoachTurn.coach_session_id == CoachSession.id)
    query = query.where(
        CoachTurn.org_id == session.org_id, CoachTurn.speaker == CoachSpeaker.CANDIDATE
    )
    if session.story_id is not None:
        query = query.where(CoachSession.story_id == session.story_id)
    else:
        query = query.where(CoachSession.id == session.id)
    texts = (await db.scalars(query)).all()
    return "\n".join(_normal(t) for t in texts)


def elapsed_ms(session: CoachSession, now: datetime | None = None) -> int:
    started = session.started_at
    if started is None:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, int(((now or datetime.now(UTC)) - started).total_seconds() * 1000))


def session_minutes(turns: Sequence[CoachTurn]) -> int:
    """Whole minutes from the start to the last turn, rounded up. An idle tab left open does
    not add minutes."""
    last = max((t.end_ms for t in turns), default=0)
    return math.ceil(last / 60000)


def add_turn(
    db: AsyncSession,
    session: CoachSession,
    turns: list[CoachTurn],
    speaker: CoachSpeaker,
    text: str,
) -> CoachTurn:
    ms = elapsed_ms(session)
    turn = CoachTurn(
        id=uuid.uuid4(),
        org_id=session.org_id,
        coach_session_id=session.id,
        seq=(turns[-1].seq + 1) if turns else 1,
        speaker=speaker,
        text=text,
        start_ms=ms,
        end_ms=ms,
    )
    db.add(turn)
    turns.append(turn)
    return turn


async def run_turn(
    db: AsyncSession,
    gateway: ModelGateway,
    session: CoachSession,
    story: StoryRow,
    turns: list[CoachTurn],
    text: str,
    prompt_refs: set[str],
) -> TurnResult:
    """One candidate turn and the coach's reply. Saves both turns and the story; the caller
    commits. `turns` is the session's turns so far, in order, and gets the new ones."""
    asked = next((t.text for t in reversed(turns) if t.speaker == CoachSpeaker.COACH), "")
    order = asks(story)
    messages = turn_messages(session, story, turns, text, order)
    candidate = add_turn(db, session, turns, CoachSpeaker.CANDIDATE, text)
    await db.flush()

    async def reply() -> CoachReply | None:
        try:
            done = await gateway.complete(Role.COACH, messages, output_type=CoachReply)
        except Exception:
            log.warning(
                "coach reply failed for %s; asking the fixed line", session.id, exc_info=True
            )
            return None
        prompt_refs.update(done.prompt_refs)
        return done.output

    with usage_context(session.org_id):  # OB-2: role coach; usage_events.session_id is NULL
        conduct, raw = await asyncio.gather(check_turn(gateway, asked, text), reply())
    prompt_refs.add(load_prompt(Role.COACH, f"style_{session.style.value}").ref)

    if conduct != AnswerConduct.OK:
        count = strikes(turns) + 1
        ended = count > MAX_CONDUCT_WARNINGS
        line = (
            _CLOSE[conduct]
            if ended
            else warning(conduct, last=count == MAX_CONDUCT_WARNINGS, ask=order[0])
        )
        coach = add_turn(db, session, turns, CoachSpeaker.COACH, line)
        if ended:
            session.status = CoachSessionStatus.ENDED
            session.ended_at = datetime.now(UTC)
        return TurnResult(
            reply=CoachReply(message=line, missing=missing_parts(story)),
            ask=order[0],
            conduct=conduct,
            ended=ended,
            turns=[candidate, coach],
        )

    dropped: list[str] = []
    kept: list[StoryPartUpdate] = []
    if raw is not None:
        said = await candidate_words(db, session)
        for update in raw.parts:
            why = backed(update, said)
            if why is None:
                kept.append(update)
            else:
                dropped.append(f"{update.part.value}: {why}")
        if dropped:
            log.warning("coach %s dropped part updates: %s", session.id, "; ".join(dropped))
        for update in kept:
            setattr(story, update.part.value, update.text)
        story.skills = merge_skills(story.skills, raw.skills)
    next_order = asks(story)
    message = (
        styled(one_question(raw.message), session.style)
        if raw is not None
        else ASK_LINES[next_order[0]]
    )
    if not message:
        message = ASK_LINES[next_order[0]]
    coach = add_turn(db, session, turns, CoachSpeaker.COACH, message)
    out = CoachReply(
        message=message,
        parts=kept,
        missing=missing_parts(story),
        skills=[Competency(s) for s in story.skills],
    )
    return TurnResult(reply=out, ask=next_order[0], dropped=dropped, turns=[candidate, coach])
