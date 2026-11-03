"""Plain text from the light Markdown users write (SC-18, D-14): bold, italic and bullet or
numbered lists. Speech, scoring, word counts and quote matching use plain text."""

from __future__ import annotations

import re

_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1|(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\3(?![\w*])")
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
SENTENCE_END = (".", "!", "?", "…", ":")


def strip_markdown(text: str) -> str:
    """D-14, SC-18: plain text for speech, scoring, word counts and quotes. Bold, italic and list
    markers go; the line breaks become spaces."""
    text = _LIST_MARK.sub("", text)
    previous = None
    while previous != text:  # nested emphasis, for example ***both***
        previous = text
        text = _EMPHASIS.sub(lambda m: m.group(2) or m.group(4), text)
    return " ".join(text.split())
