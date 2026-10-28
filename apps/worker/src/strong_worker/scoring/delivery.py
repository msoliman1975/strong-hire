"""Delivery metrics per answer (DM-1): speaking pace and filler words, from text and timestamps.

No model call and no audio: each answer is the candidate's turns for one question, and its
duration is the sum of those turns' `end_ms - start_ms`. Words per minute and fillers per minute
divide by that speaking time, so the interviewer's turns and the pauses between turns do not count.

Text-channel sessions (PL-7) are skipped: their timestamps measure typing, not speech. The answers
then keep `delivery = None`, and the debrief says why (DM-2).
"""

from __future__ import annotations

import re
from collections import defaultdict

from strong_core.schemas import DeliveryMetrics, Scorecard, SessionChannel, Speaker, Turn

# The fixed English filler list. Each entry is matched as whole words, case-insensitive.
# "like" is in the list only as a filler; see _LIKE_FILLER for when it counts.
FILLERS: tuple[str, ...] = ("um", "uh", "like", "you know", "basically", "sort of")

_WORD = re.compile(r"[A-Za-z0-9']+")
_PHRASES = [
    re.compile(r"\b" + r"\s+".join(map(re.escape, f.split())) + r"\b", re.IGNORECASE)
    for f in FILLERS
    if f != "like"
]
# "like" is a filler when a comma sets it off: "it was, like, slow" or "Like, we shipped it".
# "I like Go" and "looks like a race" do not count. A transcript without punctuation
# undercounts, which is the safe direction for a note shown to the candidate.
_LIKE_FILLER = re.compile(r",\s*like\b|\blike\s*,", re.IGNORECASE)


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def count_fillers(text: str) -> int:
    count = sum(len(p.findall(text)) for p in _PHRASES)
    return count + len(_LIKE_FILLER.findall(text))


def answer_metrics(turns: list[Turn]) -> DeliveryMetrics | None:
    """Metrics for one answer's candidate turns, or None when there is no speaking time."""
    duration_ms = sum(t.end_ms - t.start_ms for t in turns)
    if duration_ms <= 0:
        return None
    minutes = duration_ms / 60_000
    words = sum(count_words(t.text) for t in turns)
    fillers = sum(count_fillers(t.text) for t in turns)
    return DeliveryMetrics(
        words_per_minute=round(words / minutes, 1),
        fillers_per_minute=round(fillers / minutes, 1),
        duration_seconds=round(duration_ms / 1000, 1),
    )


def delivery_by_question(turns: list[Turn]) -> dict[str, DeliveryMetrics]:
    by_question: dict[str, list[Turn]] = defaultdict(list)
    for turn in turns:
        if turn.speaker == Speaker.CANDIDATE and turn.question_ref is not None:
            by_question[turn.question_ref].append(turn)
    metrics = {ref: answer_metrics(answer) for ref, answer in by_question.items()}
    return {ref: m for ref, m in metrics.items() if m is not None}


def with_delivery(card: Scorecard, turns: list[Turn], channel: SessionChannel) -> Scorecard:
    """The scorecard with `delivery` set on each answer that has speaking time (DM-1)."""
    if channel == SessionChannel.TEXT:
        return card
    metrics = delivery_by_question(turns)
    per_question = [
        q.model_copy(update={"delivery": metrics.get(q.question_ref)}) for q in card.per_question
    ]
    return card.model_copy(update={"per_question": per_question})
