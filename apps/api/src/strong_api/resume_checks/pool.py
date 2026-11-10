"""CS-1 to CS-4: story ideas pooled across every resume of the user.

Each resume in the CV library is its own row, so the same achievement shows up once per resume
version, often reworded. The pool groups those lines into one idea:

- lines with the same normalized text are the same idea (the rule half);
- a story_idea suggestion whose `payload.same_as` names an earlier suggestion is the same idea
  as it (the matcher half, CS-2: the worker sets it when the wording differs).

An idea is used when any of its suggestions is linked to a story (crafted from it, or matched to
it by the worker), or a story's parts quote any of its lines. It is dismissed when any of its
suggestions is dismissed, on any resume (CS-3). Deleted resumes still count: their dismissals and
links keep the idea from coming back on a newer version.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from strong_api.resume_checks.story_ideas import Achievement, achievements, normalize
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import Competency, Resume, StoryIdeaPayload, SuggestionStatus


@dataclass(frozen=True)
class PoolLine:
    resume_id: uuid.UUID
    resume_at: datetime
    item: Achievement
    suggestion: SuggestionRow | None


@dataclass
class IdeaGroup:
    """One achievement, however many resumes it is on."""

    lines: list[PoolLine] = field(default_factory=list)
    """Lines on readable, non-deleted resumes, newest resume first."""
    suggestions: list[SuggestionRow] = field(default_factory=list)
    story: Story | None = None
    dismissed: bool = False

    @property
    def newest(self) -> PoolLine:
        return self.lines[0]

    @property
    def resume_ids(self) -> list[uuid.UUID]:
        return list(dict.fromkeys(line.resume_id for line in self.lines))

    @property
    def skills(self) -> list[Competency]:
        """Likely skills of the newest line the skills job has seen."""
        for line in self.lines:
            if line.suggestion is not None:
                found = StoryIdeaPayload.model_validate(line.suggestion.payload).skills
                if found:
                    return found
        return []

    @property
    def pending(self) -> bool:
        """The skills job has not seen one of its lines yet."""
        return any(line.suggestion is None for line in self.lines)


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _story_text(story: Story) -> str:
    return normalize(
        " ".join(
            p or ""
            for p in (story.context, story.stakes, story.action, story.result, story.reflection)
        )
    )


@dataclass
class IdeaPool:
    groups: list[IdeaGroup]
    by_line: dict[tuple[uuid.UUID, str], IdeaGroup]
    """(resume id, resume_line_ref) to its group."""

    def group_of(self, resume_id: uuid.UUID, ref: str) -> IdeaGroup | None:
        return self.by_line.get((resume_id, ref))


def build_pool(
    resumes: Iterable[ResumeRow],
    suggestions: Iterable[SuggestionRow],
    stories: Sequence[Story],
) -> IdeaPool:
    """Group every achievement line of `resumes` (readable, not deleted) with the user's
    story_idea `suggestions` (on any resume, deleted ones too). `stories` are the stories that
    can use an idea: not deleted (an archived story still tells it)."""
    suggestions = list(suggestions)
    by_resume_text: dict[tuple[uuid.UUID, str], SuggestionRow] = {}
    for s in suggestions:
        if s.source_resume_id is not None:
            key = (s.source_resume_id, normalize(str(s.payload.get("achievement", ""))))
            by_resume_text.setdefault(key, s)

    union = _Union()
    for s in suggestions:
        union.join(f"s:{s.id}", f"t:{normalize(str(s.payload.get('achievement', '')))}")
        same_as = s.payload.get("same_as")
        if same_as:
            union.join(f"s:{s.id}", f"s:{same_as}")

    lines: list[PoolLine] = []
    for row in sorted(resumes, key=lambda r: (r.uploaded_at, str(r.id)), reverse=True):
        if row.parsed_json is None or row.deleted_at is not None:
            continue
        for item in achievements(Resume.model_validate(row.parsed_json)):
            text = normalize(item.text)
            suggestion = by_resume_text.get((row.id, text))
            line = PoolLine(row.id, row.uploaded_at, item, suggestion)
            lines.append(line)
            node = f"l:{row.id}:{item.ref}"
            union.join(node, f"t:{text}")
            if suggestion is not None:
                union.join(node, f"s:{suggestion.id}")

    groups: dict[str, IdeaGroup] = {}
    for line in lines:
        groups.setdefault(
            union.find(f"l:{line.resume_id}:{line.item.ref}"), IdeaGroup()
        ).lines.append(line)
    for s in suggestions:
        group = groups.get(union.find(f"s:{s.id}"))
        if group is not None:
            group.suggestions.append(s)

    live = {s.id: s for s in stories}
    texts = [(s, _story_text(s)) for s in stories]
    for group in groups.values():
        group.dismissed = any(s.status == SuggestionStatus.DISMISSED for s in group.suggestions)
        linked = (live.get(s.story_id) for s in group.suggestions if s.story_id is not None)
        group.story = next((s for s in linked if s is not None), None)
        if group.story is None:
            keys = {normalize(line.item.text) for line in group.lines}
            group.story = next((s for s, t in texts if any(k and k in t for k in keys)), None)

    by_line = {
        (line.resume_id, line.item.ref): group for group in groups.values() for line in group.lines
    }
    return IdeaPool(groups=list(groups.values()), by_line=by_line)
