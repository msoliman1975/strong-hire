"""IV-12: candidate turns that are outside the interview or inappropriate.

Two checks run on a candidate turn before the interviewer replies:

- `screen_turn`: a fixed list of clear abuse ("f*** you", threats). It needs no model call and
  runs in every phase but the wrap-up.
- The answer check (Interviewer.check_answer): the interviewer model returns an AnswerCheck. It
  runs in CORE and in the candidate questions phase, at the same time as the probe decision, so
  it adds no wait in CORE. Small talk is not checked by the model. When the call fails, the turn
  is ok.

A weak, vague or off-topic answer is ok here; IV-3 probes it. Only a turn about something outside
the interview, or an inappropriate one, counts. The controller counts these turns. The first and
the second get a polite warning, and the second says that the next one ends the interview. The
third closes the interview. The lines are fixed text, never model output, so a confused model
cannot make them rude or wrong.
"""

from __future__ import annotations

import re

from strong_core.schemas import AnswerConduct, Phase

MAX_CONDUCT_WARNINGS = 2  # the turn after the last warning closes the interview

_ABUSE = re.compile(
    r"""
    \bf+u+c*k+(ing)?\s+(you|u|off|this\ interview)\b
    | \bgo\ to\ hell\b
    | \b(mother\s?fucker|cunt|dickhead|son\ of\ a\ bitch)\b
    | \b(you('re|\ are)|ur)\s+(an?\s+)?(fucking\s+|f\*+ing\s+)?(idiot|moron|retard|bitch|asshole)\b
    | \bi('ll|\ will|\ am\ going\ to|'m\ going\ to)\s+(kill|hurt|beat\ up)\s+you\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_FIRST: dict[AnswerConduct, str] = {
    AnswerConduct.OFF_SCOPE: "Let's keep our time for the interview.",
    AnswerConduct.INAPPROPRIATE: "Let's keep our conversation respectful and professional.",
}
_LAST = "This is my second reminder. If it happens again, I will end the interview."
_CLOSE: dict[AnswerConduct, str] = {
    AnswerConduct.OFF_SCOPE: (
        "I'm going to end the interview here, because we kept moving away from the interview. "
        "You can start a new session when you're ready. Goodbye."
    ),
    AnswerConduct.INAPPROPRIATE: (
        "I'm going to end the interview here, because the conversation did not stay "
        "professional. You can start a new session when you're ready. Goodbye."
    ),
}


def screen_turn(text: str) -> AnswerConduct | None:
    """INAPPROPRIATE for clear abuse in the fixed list, else None (the model check decides)."""
    return AnswerConduct.INAPPROPRIATE if _ABUSE.search(text.replace("\u2019", "'")) else None


def warning_line(conduct: AnswerConduct, *, last: bool, phase: Phase, question: str | None) -> str:
    """The polite warning, then the way back into the interview."""
    parts = [_FIRST[conduct]]
    if last:
        parts.append(_LAST)
    if phase == Phase.CORE and question:
        parts.append(f"Back to my question: {question}")
    elif phase == Phase.CANDIDATE_QUESTIONS:
        parts.append("Do you have a question about the role, the team or the company?")
    else:
        parts.append("Let's continue.")
    return " ".join(parts)


def closing_line(conduct: AnswerConduct) -> str:
    return _CLOSE[conduct]
