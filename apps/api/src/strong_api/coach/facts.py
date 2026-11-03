"""SC-15 (CO-9, D-6): Strova may reword, but every fact in her text must come from the user.

`new_facts(text, said)` lists what Strova's text claims that the user's words (`said`, as
`engine.normal` writes them) do not hold:

- a number the user never gave ("35" when they said "between 30 and 40");
- a hedged number made exact: the user said "about 40" and Strova wrote "40" with no hedge;
- a proper noun or a tool the user never named ("Kafka", "PostgreSQL", "Stripe"): a capitalized
  word that does not start a sentence, or a word with a capital or digit inside it.

Result claims ride on numbers and names, so they are covered by the two rules above. Wording is
free: the check is on facts, never on phrasing.
"""

from __future__ import annotations

import re

from strong_api.markdown import strip_markdown

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_HEDGE = (
    r"about|around|roughly|approximately|approx\.?|nearly|almost|close to|up to|over|under"
    r"|more than|less than|at least|at most|some|~"
)
_HEDGED = re.compile(rf"(?:{_HEDGE})\s*(?:\$|€|£)?\s*(\d+(?:[.,]\d+)*)", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-']*[A-Za-z0-9+#]|[A-Za-z]")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+|\n\s*)$")
# Words that may start with a capital anywhere: "I", and its contractions.
_ALWAYS_CAPS = {"i", "i'm", "i'd", "i've", "i'll"}


def _numbers(text: str) -> list[str]:
    return _NUMBER.findall(text)


def _names(text: str) -> list[str]:
    """Capitalized words that do not open a sentence, and words with an inner capital or digit."""
    out = []
    for match in _WORD.finditer(text):
        word = match.group(0).rstrip(".")
        lower = word.lower()
        if lower in _ALWAYS_CAPS or len(word) < 2:
            continue
        inner = any(c.isupper() for c in word[1:]) or (
            any(c.isdigit() for c in word) and any(c.isalpha() for c in word)
        )
        opens = bool(_SENTENCE_START.search(text[: match.start()]))
        if inner or (word[0].isupper() and not opens):
            out.append(word)
    return out


def new_facts(text: str, said: str) -> list[str]:
    """SC-15: the facts in `text` that the user's words (`said`, normalized) do not hold."""
    plain = strip_markdown(text)
    words = {w.strip(".,'-%$") for w in said.split()}
    joined = f" {said} "
    found: list[str] = []
    for number in _numbers(plain):
        if number not in said:
            found.append(f"number {number}")
    hedged_by_user = {m.group(1) for m in _HEDGED.finditer(said)}
    hedged_here = {m.group(1) for m in _HEDGED.finditer(plain)}
    for number in _numbers(plain):
        exact_in_said = re.search(rf"(?<![\w.,]){re.escape(number)}(?![\w])", said) is not None
        if number in hedged_by_user and number not in hedged_here and exact_in_said:
            # The user only ever gave it as an estimate.
            unhedged = [
                m
                for m in re.finditer(rf"(?<![\w.,]){re.escape(number)}(?![\w])", said)
                if not re.search(rf"(?:{_HEDGE})\s*(?:\$|€|£)?\s*$", said[: m.start()], re.I)
            ]
            if not unhedged:
                found.append(f"{number} made exact (the user said about {number})")
    for name in _names(plain):
        lower = name.lower()
        if lower not in words and f" {lower} " not in joined and lower.rstrip("s") not in words:
            found.append(f"name {name}")
    return list(dict.fromkeys(found))
