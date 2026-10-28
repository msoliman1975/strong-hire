"""CO-8: the coach's 60-second and full versions of a story, from the candidate's own words.

The coach role writes both versions with prompt coach/story_versions. Code then checks each one
against what the candidate said (the story's parts and its takes):
- every quote is the candidate's words (the coach engine's quote match, CO-3);
- every number in the text is in the quotes, as digits or as a word ("5" and "five");
- every sentence is backed by the quotes: at least SUPPORT_SHARE of its content words appear in
  them (a light stem, so "payments" matches "payment"). A sentence the candidate never said, such
  as an added achievement, has almost none of its words in the quotes.
A version that fails is rejected. The coach is asked once more with the problems; if the second
answer fails too, nothing is returned.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from strong_api.coach.engine import PARTS, _normal, part_text, quote_found
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import StoryVersion, StoryVersions

log = logging.getLogger(__name__)

SUPPORT_SHARE = 0.5
STEM_CHARS = 5
TAKES_IN_PROMPT = 5  # the most recent takes the coach reads

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
) | {p.value for p in PARTS}  # the full version labels its parts ("Context: ...")


@dataclass
class VersionsResult:
    versions: StoryVersions | None
    problems: list[str] = field(default_factory=list)
    prompt_refs: tuple[str, ...] = ()
    calls: int = 0


def sources(story: StoryRow, takes: Sequence[str]) -> list[str]:
    """What the candidate said on this story: its filled parts, then its takes."""
    parts = [t for p in PARTS if (t := part_text(story, p)) is not None]
    return [*parts, *(t for t in takes if t.strip())]


def said_text(texts: Sequence[str]) -> str:
    return "\n".join(_normal(t) for t in texts)


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
    words = _WORD.findall(_normal(text))
    return [_stem(w) for w in words if w not in _STOPWORDS and len(w.strip("'")) > 1]


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(" ".join(text.split())) if s.strip()]


def _number_backed(number: str, quoted: str) -> bool:
    if number in quoted:
        return True
    plain = number.replace(",", "")
    if plain.isdigit() and int(plain) < len(_NUMBER_WORDS):
        return re.search(rf"\b{_NUMBER_WORDS[int(plain)]}\b", quoted) is not None
    return False


def check_version(name: str, version: StoryVersion, said: str) -> list[str]:
    """Why the version is not the candidate's own words; empty when it is."""
    problems = [
        f"{name}: quote not found: {q[:80]!r}" for q in version.quotes if not quote_found(q, said)
    ]
    quoted = " ".join(_normal(q) for q in version.quotes)
    for number in _NUMBER.findall(version.text):
        if not _number_backed(number, quoted):
            problems.append(f"{name}: number not in the quotes: {number}")
    backing = set(content_words(quoted))
    for sentence in sentences(version.text):
        words = content_words(sentence)
        if not words:
            continue
        share = sum(w in backing for w in words) / len(words)
        if share < SUPPORT_SHARE:
            problems.append(f"{name}: sentence not in the candidate's words: {sentence[:80]!r}")
    return problems


def check_versions(versions: StoryVersions, said: str) -> list[str]:
    return [
        *check_version("sixty_second", versions.sixty_second, said),
        *check_version("full", versions.full, said),
    ]


def _render_story(story: StoryRow) -> str:
    lines = [f"Title: {story.title}"]
    lines += [f"{p.value}: {part_text(story, p) or '(empty)'}" for p in PARTS]
    return "\n".join(lines)


def version_messages(story: StoryRow, takes: Sequence[str]) -> list[Message]:
    recent = [t for t in takes if t.strip()][-TAKES_IN_PROMPT:]
    return [
        load_prompt(Role.COACH, "story_versions").message("system"),
        load_prompt(Role.COACH, "story_versions_input").message(
            "user",
            story=_render_story(story),
            takes="\n\n".join(f"Take {i}: {t}" for i, t in enumerate(recent, 1)) or "(none)",
        ),
    ]


async def write_versions(
    gateway: ModelGateway, story: StoryRow, takes: Sequence[str]
) -> VersionsResult:
    """CO-8: both versions, checked against the candidate's words; None after a second miss."""
    said = said_text(sources(story, takes))
    messages = version_messages(story, takes)
    refs: list[str] = []
    problems: list[str] = []
    for attempt in (1, 2):
        done = await gateway.complete(Role.COACH, messages, output_type=StoryVersions)
        refs += done.prompt_refs
        problems = check_versions(done.output, said)
        if not problems:
            return VersionsResult(done.output, [], tuple(dict.fromkeys(refs)), attempt)
        log.info("story versions rejected (attempt %d): %s", attempt, "; ".join(problems))
        messages = [
            *messages,
            Message(role="assistant", content=done.output.model_dump_json()),
            load_prompt(Role.COACH, "story_versions_fix").message(
                "user", problems="\n".join(f"- {p}" for p in problems)
            ),
        ]
    return VersionsResult(None, problems, tuple(dict.fromkeys(refs)), 2)
