"""RM-4: the rule-based half of story ideas, for the API.

The same rules as strong_worker.inputs.story_ideas (the API image has no worker code); a test
checks the two stay identical. The worker job adds the likely skills.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from strong_core.schemas import Resume, StoryPart


@dataclass(frozen=True)
class Achievement:
    ref: str
    """Where the line is in schemas.Resume: roles[<i>].achievements[<j>]."""
    text: str
    role: str
    """"Title, Company"."""


def achievements(resume: Resume) -> list[Achievement]:
    """Every non-empty achievement line, in resume order."""
    found = []
    for i, role in enumerate(resume.roles):
        for j, text in enumerate(role.achievements):
            if text.strip():
                found.append(
                    Achievement(
                        f"roles[{i}].achievements[{j}]",
                        text.strip(),
                        f"{role.title}, {role.company}",
                    )
                )
    return found


def normalize(text: str) -> str:
    """Achievements match by their text, ignoring case, spacing and end punctuation."""
    return re.sub(r"\s+", " ", text).strip().strip(".;").lower()


# Irregular past tenses that open resume lines in the first person ("Led", "Built", "Ran").
_IRREGULAR_PAST = {
    "led", "built", "ran", "wrote", "drove", "grew", "cut", "made", "took", "won", "set",
    "began", "brought", "sold", "taught", "kept", "found", "held", "spoke", "chose", "rebuilt",
    "rewrote", "overhauled", "oversaw", "undertook", "shut", "split", "spun", "put", "met",
}  # fmt: skip


def missing_parts(text: str) -> list[StoryPart]:
    """What a story built on this line still needs. A resume line rarely says why it mattered or
    what the user learned, so stakes and reflection are always missing. Action is missing too
    when the line does not open with a verb in the first person past tense ("Led", "Cut"), or
    say "I"."""
    words = re.findall(r"[A-Za-z']+", text)
    first = words[0].lower() if words else ""
    has_action = (
        first.endswith("ed") or first in _IRREGULAR_PAST or re.search(r"\bI\b", text) is not None
    )
    parts = [StoryPart.STAKES, StoryPart.REFLECTION]
    if not has_action:
        parts.insert(0, StoryPart.ACTION)
    return parts


def idea_reason(item: Achievement) -> str:
    return f"An achievement on your resume ({item.role}) that no story tells yet."
