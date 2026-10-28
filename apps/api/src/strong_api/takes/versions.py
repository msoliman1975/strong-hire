"""CO-8: the coach's 60-second and full versions of a story, from the candidate's own words.

The coach role writes both versions with prompt coach/story_versions. It reads the story's parts
only as an outline: in a coach story the coach wrote them, so they are not the candidate's words.
Every quote must come from what the candidate said themself (`said`): their coach turns, the
interview answer a story was saved from, and their takes (strong_api.takes.words). Code then
checks each version against those words only:
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
SAID_PROMPT_CHARS = 16000  # the candidate's most recent words the coach reads

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


def recent_words(said: Sequence[str], budget: int = SAID_PROMPT_CHARS) -> list[str]:
    """The newest of the candidate's texts that fit in `budget` characters, oldest first."""
    out: list[str] = []
    used = 0
    for text in reversed([t.strip() for t in said if t.strip()]):
        if out and used + len(text) > budget:
            break
        out.append(text)
        used += len(text)
    return out[::-1]


def version_messages(story: StoryRow, said: Sequence[str]) -> list[Message]:
    words = recent_words(said)
    return [
        load_prompt(Role.COACH, "story_versions").message("system"),
        load_prompt(Role.COACH, "story_versions_input").message(
            "user",
            story=_render_story(story),
            said="\n\n".join(f"{i}. {t}" for i, t in enumerate(words, 1)) or "(nothing yet)",
        ),
    ]


async def write_versions(
    gateway: ModelGateway, story: StoryRow, said_texts: Sequence[str]
) -> VersionsResult:
    """CO-8: both versions, checked against `said_texts`, the candidate's own words only (never
    the story's parts); None after a second miss."""
    said = said_text(said_texts)
    messages = version_messages(story, said_texts)
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
