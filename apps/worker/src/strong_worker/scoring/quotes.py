"""Quote validation: every quote in a scorecard must appear in what the candidate said (FB-2).

The check compares whole words. It ignores case, punctuation, spacing, and curly versus straight
apostrophes. A quote may skip words with an ellipsis ("I wrote ... the cutover"): each part must
appear, in order, in the same candidate turn. A quote needs at least MIN_WORDS words, so a bare
"yes" cannot back a score. Interviewer lines never count as evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from strong_core.schemas import Speaker, Turn

MIN_WORDS = 3

_ELLIPSIS = re.compile(r"\.\.\.|…")
_NOT_WORD = re.compile(r"[^\w']+")
_APOSTROPHES = str.maketrans({0x2018: "'", 0x2019: "'"})


def words(text: str) -> str:
    """Lower-case words separated by single spaces, with a space at each end."""
    text = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES)
    tokens = [t.strip("'") for t in _NOT_WORD.split(text.lower())]
    return " " + " ".join(t for t in tokens if t) + " "


class QuoteChecker:
    def __init__(self, turns: Sequence[Turn]) -> None:
        self._answers = [words(t.text) for t in turns if t.speaker == Speaker.CANDIDATE]

    def is_valid(self, quote: str) -> bool:
        parts = [words(p) for p in _ELLIPSIS.split(quote)]
        parts = [p for p in parts if p.strip()]
        if not parts or sum(len(p.split()) for p in parts) < MIN_WORDS:
            return False
        return any(_in_order(parts, answer) for answer in self._answers)

    def keep_valid(self, quotes: Sequence[str]) -> tuple[list[str], list[str]]:
        """(valid quotes without repeats, invalid quotes)."""
        good: list[str] = []
        bad: list[str] = []
        for q in quotes:
            if self.is_valid(q):
                if q not in good:
                    good.append(q)
            else:
                bad.append(q)
        return good, bad


def _in_order(parts: list[str], text: str) -> bool:
    pos = 0
    for part in parts:
        found = text.find(part, pos)
        if found < 0:
            return False
        pos = found + len(part) - 1  # parts share the space between them
    return True
