"""Compact text views of the posting and resume for planner prompts.

The planner reads the parsed contracts, not the raw documents: they were sanitized at
extraction (IN-1 to IN-3), and they are shorter, which keeps local models inside their context.
"""

from __future__ import annotations

from strong_core.schemas import JobPosting, Resume
from strong_worker.inputs.sanitize import sanitize_untrusted

MAX_CONTEXT_CHARS = 1500


def resume_text(resume: Resume) -> str:
    lines: list[str] = []
    if resume.summary:
        lines.append(f"Summary: {resume.summary}")
    for role in resume.roles:
        lines.append(
            f"Role: {role.title}, {role.company} ({role.start or '?'} to {role.end or 'now'})"
        )
        lines += [f"  - {a}" for a in role.achievements]
        if role.skills:
            lines.append(f"  Skills: {', '.join(role.skills)}")
    if resume.skills:
        lines.append(f"Skills: {', '.join(resume.skills)}")
    for e in resume.education:
        parts = [p for p in (e.degree, e.field_of_study) if p]
        lines.append(f"Education: {' '.join(parts) or 'Studies'}, {e.institution}")
    if resume.certifications:
        lines.append(f"Certifications: {', '.join(resume.certifications)}")
    return "\n".join(lines) or "(empty resume)"


def posting_text(posting: JobPosting) -> str:
    lines = [f"Title: {posting.title}", f"Company: {posting.company_name}"]
    if posting.level_label or posting.level:
        lines.append(f"Level: {posting.level_label or posting.level}")
    if posting.team:
        lines.append(f"Team: {posting.team}")
    if posting.responsibilities:
        lines.append("Responsibilities:")
        lines += [f"  - {r}" for r in posting.responsibilities]
    return "\n".join(lines)


def context_text(context_notes: str | None) -> str:
    """Optional user context (IN-4). It is user text, so it is sanitized and kept short."""
    if not context_notes:
        return "(none)"
    return sanitize_untrusted(context_notes, max_chars=MAX_CONTEXT_CHARS).text or "(none)"
