"""Job posting (IN-2) and resume (IN-3) extraction with the extractor role through the gateway.

Untrusted text is sanitized, then placed only in the user message inside a data block. The
system prompt is a fixed template with no placeholders, so input text can never change it.
The gateway validates the output against the contract (and retries once on a schema error);
this module retries the whole call once more on any failure and drops list items that still
look like instructions to a model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import Confidence, JobPosting, Resume
from strong_worker.inputs.confidence import job_posting_confidence, resume_confidence
from strong_worker.inputs.sanitize import drop_injected_items, sanitize_untrusted

log = logging.getLogger(__name__)

MIN_POSTING_CHARS = 80
MIN_RESUME_CHARS = 80
ATTEMPTS = 2  # the first call plus one retry


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Extraction[T]:
    output: T
    confidence: dict[str, Confidence]
    flags: list[str] = field(default_factory=list)
    model: str = ""
    prompt_refs: tuple[str, ...] = ()
    attempts: int = 1

    def summary(self) -> dict[str, object]:
        """JSON-safe description for the Arq job result."""
        return {
            "confidence": {k: v.value for k, v in self.confidence.items()},
            "flags": self.flags,
            "model": self.model,
            "prompt_refs": list(self.prompt_refs),
            "attempts": self.attempts,
        }


def build_job_posting_messages(text: str) -> list[Message]:
    return [
        load_prompt(Role.EXTRACTOR, "job_posting").message("system"),
        load_prompt(Role.EXTRACTOR, "job_posting_input").message("user", posting=text),
    ]


def build_resume_messages(text: str) -> list[Message]:
    return [
        load_prompt(Role.EXTRACTOR, "resume").message("system"),
        load_prompt(Role.EXTRACTOR, "resume_input").message("user", resume=text),
    ]


async def extract_job_posting(
    gateway: ModelGateway, text: str, *, source_url: str | None = None
) -> Extraction[JobPosting]:
    clean = sanitize_untrusted(text)
    if len(clean.text) < MIN_POSTING_CHARS:
        raise ExtractionError(
            f"The posting text has {len(clean.text)} characters; at least "
            f"{MIN_POSTING_CHARS} are needed."
        )
    messages = build_job_posting_messages(clean.text)
    posting, model, refs, attempts = await _complete(
        gateway, messages, JobPosting, _job_posting_problems
    )

    flags = clean.flags
    updates: dict[str, object] = {"source_url": source_url}
    for name in ("must_have_skills", "nice_to_have_skills", "responsibilities"):
        kept, dropped = drop_injected_items(getattr(posting, name))
        if dropped:
            updates[name] = kept
            flags += [f"dropped_from_output: {d[:120]}" for d in dropped]
    posting = posting.model_copy(update=updates)
    return Extraction(
        posting, job_posting_confidence(posting, clean.text), flags, model, refs, attempts
    )


async def extract_resume(gateway: ModelGateway, text: str) -> Extraction[Resume]:
    clean = sanitize_untrusted(text)
    if len(clean.text) < MIN_RESUME_CHARS:
        raise ExtractionError(
            f"The resume text has {len(clean.text)} characters; at least "
            f"{MIN_RESUME_CHARS} are needed."
        )
    messages = build_resume_messages(clean.text)
    resume, model, refs, attempts = await _complete(gateway, messages, Resume, _resume_problems)

    flags = clean.flags
    skills, dropped = drop_injected_items(resume.skills)
    roles = []
    for role in resume.roles:
        achievements, dropped_here = drop_injected_items(role.achievements)
        dropped += dropped_here
        roles.append(role.model_copy(update={"achievements": achievements}))
    summary = resume.summary
    if summary and drop_injected_items([summary])[1]:
        dropped.append(summary)
        summary = None
    flags += [f"dropped_from_output: {d[:120]}" for d in dropped]
    resume = resume.model_copy(update={"skills": skills, "roles": roles, "summary": summary})
    suspect = attribution_flags(resume)
    if suspect:
        log.warning("resume extraction looks misfiled: %s", "; ".join(suspect))
    flags += suspect
    return Extraction(resume, resume_confidence(resume, clean.text), flags, model, refs, attempts)


async def _complete[T: (JobPosting, Resume)](
    gateway: ModelGateway,
    messages: list[Message],
    output_type: type[T],
    problems: Callable[[T], list[str]],
) -> tuple[T, str, tuple[str, ...], int]:
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            done = await gateway.complete(Role.EXTRACTOR, messages, output_type=output_type)
        except Exception as exc:  # gateway, network or validation error: retry once
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}"[:300])
            log.warning("extractor call failed (%s), attempt %d", type(exc).__name__, attempt)
            continue
        found = problems(done.output)
        if not found:
            return done.output, done.model, done.prompt_refs, attempt
        errors.append(f"attempt {attempt}: " + "; ".join(found))
    raise ExtractionError(
        f"{output_type.__name__} extraction failed after {ATTEMPTS} attempts: " + " | ".join(errors)
    )


def _job_posting_problems(posting: JobPosting) -> list[str]:
    found = []
    if not (posting.must_have_skills or posting.responsibilities):
        found.append("no skills and no responsibilities")
    return found


def _resume_problems(resume: Resume) -> list[str]:
    found = []
    if not (resume.roles or resume.skills or resume.education):
        found.append("no roles, skills or education")
    for role in resume.roles:
        if role.start and role.end and role.end < role.start:
            found.append(f"role '{role.title}' ends before it starts")
    return found


SUSPECT_MIN_NEIGHBOR = 3  # achievements the next role must have before an empty role looks odd


def attribution_flags(resume: Resume) -> list[str]:
    """Confidence flags for achievements that may sit under the wrong role. Never a failure.

    A role with dates but no achievements, right above a role with several, often means the
    reader or the model moved the first role's lines into the next one (a PDF read out of
    order). The flag tells the user to check the CV; the extraction is kept as it is.
    """
    flags = []
    roles = resume.roles
    for role, below in pairwise(roles):
        dated = role.start is not None or role.end is not None
        if dated and not role.achievements and len(below.achievements) >= SUSPECT_MIN_NEIGHBOR:
            flags.append(
                f"attribution_suspect: '{role.title}' at '{role.company}' has no achievements "
                f"and the next role has {len(below.achievements)}"
            )
    return flags
