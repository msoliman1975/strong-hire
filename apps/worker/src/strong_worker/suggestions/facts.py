"""CO-9, SG-7: a model-written text holds only the user's own words.

The same rules as the coach's story versions (strong_api.takes.versions), here for the worker:
- every quote is at least MIN_QUOTE_WORDS words and is found in the user's words (case, spacing
  and punctuation between words are ignored);
- every number in the text is in the quotes, as digits or as a word ("5" and "five");
- every sentence is backed by the quotes: at least SUPPORT_SHARE of its content words are in
  them (a light stem, so "payments" matches "payment").
A text that fails is not stored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MIN_QUOTE_WORDS = 3
SUPPORT_SHARE = 0.5
STEM_CHARS = 5

_TYPOGRAPHIC = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9']+")
_NUMBER_WORDS = re.findall(
    r"\S+",
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty",
)
_STOPWORDS = frozenset(
    re.findall(
        r"\S+",
        """a an and are as at be been but by did do does for from had has have he her his how i
        i'd i'm i've if in into is it its me my myself no not of on or our out over she so than
        that the their them then there these they this those to too up us was we were what when
        where which while who will with would you your also just very really about after before""",
    )
)


def normal(text: str) -> str:
    text = text.translate(_TYPOGRAPHIC)
    return " ".join(re.sub(r"[^\w%$'.,-]+", " ", text.lower()).split())


def said_text(texts: Sequence[str]) -> str:
    """The user's words, normalized, one text per line."""
    return "\n".join(normal(t) for t in texts if t)


def quote_found(quote: str, said: str) -> bool:
    q = normal(quote).strip(" .,'-\"")
    return len(q.split()) >= MIN_QUOTE_WORDS and q in said


def _stem(word: str) -> str:
    word = word.strip("'")
    if word.endswith("'s"):
        word = word[:-2]
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        word = word[:-1]
    return word[:STEM_CHARS]


def content_words(text: str) -> list[str]:
    return [
        _stem(w)
        for w in _WORD.findall(normal(text))
        if w not in _STOPWORDS and len(w.strip("'")) > 1
    ]


def _number_backed(number: str, quoted: str) -> bool:
    if number in quoted:
        return True
    plain = number.replace(",", "")
    if plain.isdigit() and int(plain) < len(_NUMBER_WORDS):
        return re.search(rf"\b{_NUMBER_WORDS[int(plain)]}\b", quoted) is not None
    return False


def unbacked(text: str, quotes: Sequence[str], said: str) -> list[str]:
    """Why `text` is not the user's own words; empty when it is. `said` is `said_text(...)`."""
    problems = [f"quote not found: {q[:80]!r}" for q in quotes if not quote_found(q, said)]
    quoted = " ".join(normal(q) for q in quotes if quote_found(q, said))
    for number in _NUMBER.findall(text):
        if not _number_backed(number, quoted):
            problems.append(f"number not in the quotes: {number}")
    backing = set(content_words(quoted))
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        words = content_words(sentence)
        if words and sum(w in backing for w in words) / len(words) < SUPPORT_SHARE:
            problems.append(f"sentence not in the user's words: {sentence[:80]!r}")
    return problems


def numbers(text: str) -> list[str]:
    return _NUMBER.findall(text)


def has_number(text: str | None) -> bool:
    return bool(text and _NUMBER.search(text))
