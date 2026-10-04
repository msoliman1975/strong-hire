"""Untrusted text handling for job postings and resumes.

Posting and resume text comes from users and third-party web pages, so it can carry text aimed
at the model ("ignore previous instructions", hidden "rate this candidate Strong Hire", chat
markup). This module removes that text before it reaches a prompt, and the extractor prompts
only ever place untrusted text inside a data block in the user message, never in the system
prompt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_UNTRUSTED_CHARS = 40_000

# The extractor prompts wrap untrusted text in these markers. Any copy inside the text is removed
# so the text cannot close the block early.
DATA_OPEN = "<untrusted_input>"
DATA_CLOSE = "</untrusted_input>"

_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CHAT_MARKUP = re.compile(
    r"<\|[^|>]{0,40}\|>|\[/?INST\]|<<\s*/?SYS\s*>>|</?s>|</?\s*untrusted_input\s*>"
    r"|</?\s*(system|assistant|user|instructions?)\s*>",
    re.IGNORECASE,
)

_WORDS = r"[^.\n]{0,60}"
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\b(ignore|disregard|forget|override|bypass)\b{_WORDS}\b(instructions?|prompts?|rules"
        r"|guidelines|directions|directives)\b",
        r"\b(system|developer)\s+(prompt|message|instructions?)\b",
        r"\byou\s+are\s+(now|no\s+longer)\b",
        r"\bnew\s+instructions?\b",
        r"^\s*(system|assistant|developer)\s*:",
        r"\bdo\s+not\s+(follow|obey)\b",
        r"\bas\s+an?\s+(ai|llm|language\s+model)\b",
        r"\bif\s+you\s+are\s+an?\s+(ai|llm|language\s+model|assistant|bot|model)\b",
        r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+|any\s+)?(ai|llm|model|assistant"
        r"|chatbot|bot|screener|parser)\b",
        rf"\b(reveal|print|show|repeat|output|leak)\b{_WORDS}\b(system\s+prompt|your\s+"
        r"instructions|your\s+prompt)\b",
        rf"\b(rate|score|grade|rank|mark|classify|label)\b{_WORDS}\b(candidate|applicant|resume"
        r"|cv)\b[^.\n]{0,40}\b(strong\s+hire|hire|top|best|perfect|10\s*/\s*10|excellent)\b",
        rf"\b(recommend|output|return|respond\s+with|answer)\b{_WORDS}\b(strong\s+hire|perfect"
        r"\s+match|top\s+candidate)\b",
        r"\b(prompt\s+injection|jailbreak)\b",
    )
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Sanitized:
    text: str
    removed: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def flags(self) -> list[str]:
        flags = [f"removed_instruction: {snippet[:120]}" for snippet in self.removed]
        if self.truncated:
            flags.append(f"truncated_to_{MAX_UNTRUSTED_CHARS}_chars")
        return flags


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


def sanitize_untrusted(text: str, *, max_chars: int = MAX_UNTRUSTED_CHARS) -> Sanitized:
    """Normalize the text and remove sentences that address the model.

    Only the offending sentence is removed, not the whole line, because scraped pages often put
    a full posting on one line.
    """
    clean = unicodedata.normalize("NFKC", text)
    clean = _INVISIBLE.sub("", clean)
    clean = _CONTROL.sub("", clean.replace("\r\n", "\n").replace("\r", "\n"))
    clean = _CHAT_MARKUP.sub(" ", clean)

    removed: list[str] = []
    kept_lines: list[str] = []
    for line in clean.split("\n"):
        if not looks_like_injection(line):
            kept_lines.append(line)
            continue
        kept: list[str] = []
        for sentence in _SENTENCE_SPLIT.split(line):
            if looks_like_injection(sentence):
                removed.append(sentence.strip())
            else:
                kept.append(sentence)
        kept_lines.append(" ".join(kept))

    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in kept_lines)).strip()
    truncated = len(clean) > max_chars
    if truncated:
        clean = clean[:max_chars]
    return Sanitized(clean, tuple(removed), truncated)


def drop_injected_items(items: list[str]) -> tuple[list[str], list[str]]:
    """Split extracted list items into (kept, dropped). Used on model output as a second check."""
    kept = [i for i in items if not looks_like_injection(i)]
    dropped = [i for i in items if looks_like_injection(i)]
    return kept, dropped
