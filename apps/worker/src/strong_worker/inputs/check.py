"""IN-6, IN-7: refuse a job description or a CV input that is not that kind of document.

The extractor role reads the start of the text and returns an InputCheck: what the text looks
like, and one short sentence on why. The worker runs it before the extraction. A refused input
gets the job outcome "rejected" with a message for the user: a fixed sentence for the kind of
document, then the model's short reason.

The check must never block a real input. When the model call fails, or its answer contradicts
itself (matches is false but looks_like is the expected kind), the input is accepted. The model's
reason is untrusted, so it is cut to 200 characters and dropped when it looks like instructions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import DocumentKind, InputCheck
from strong_worker.inputs.sanitize import drop_injected_items, sanitize_untrusted

log = logging.getLogger(__name__)

CHECK_CHARS = 6000  # the start of the text is enough to tell the kind of document
Expected = Literal["job_posting", "resume"]
Source = Literal["link", "text", "file"]

_PROMPT: dict[Expected, str] = {"job_posting": "check_job_posting", "resume": "check_resume"}
_EXPECTED_KIND: dict[Expected, DocumentKind] = {
    "job_posting": DocumentKind.JOB_POSTING,
    "resume": DocumentKind.RESUME,
}
_SOURCE: dict[Source, str] = {"link": "This link", "text": "This text", "file": "This file"}

# The fixed first sentence of the message, by expected input and by what the text looks like.
_JOB_MESSAGES: dict[DocumentKind, str] = {
    DocumentKind.JOB_LIST: (
        "{source} shows a list of jobs, not one job description. Open one job and use its "
        "link, or paste its text."
    ),
    DocumentKind.RESUME: (
        "{source} looks like a CV, not a job description. Add your CV under Resumes."
    ),
    DocumentKind.COVER_LETTER: "{source} looks like a cover letter, not a job description.",
    DocumentKind.COMPANY_PAGE: (
        "{source} is a company page, not a job description. Use the link to one job posting."
    ),
    DocumentKind.ARTICLE: "{source} looks like an article, not a job description.",
    DocumentKind.ERROR_PAGE: (
        "{source} opens a sign-in or error page, so we could not find a job description. "
        "Paste the posting text instead."
    ),
}
_RESUME_MESSAGES: dict[DocumentKind, str] = {
    DocumentKind.JOB_POSTING: (
        "{source} looks like a job description, not a CV. Add it under Job descriptions."
    ),
    DocumentKind.JOB_LIST: "{source} shows a list of jobs, not a CV.",
    DocumentKind.COVER_LETTER: (
        "{source} looks like a cover letter, not a CV. Upload the CV itself."
    ),
    DocumentKind.COMPANY_PAGE: "{source} looks like a company page, not a CV.",
    DocumentKind.ARTICLE: "{source} looks like an article, not a CV.",
    DocumentKind.ERROR_PAGE: "We could not find CV text in {source_lower}.",
}
_DEFAULT: dict[Expected, str] = {
    "job_posting": "{source} does not look like a job description.",
    "resume": "{source} does not look like a CV.",
}


@dataclass(frozen=True)
class Refusal:
    """Why the input was refused, for the job result."""

    looks_like: DocumentKind
    message: str
    reason: str  # the model's reason after the checks; may be empty
    model: str
    prompt_refs: tuple[str, ...]

    def result(self) -> dict[str, object]:
        """The JSON-safe Arq job result."""
        return {
            "outcome": "rejected",
            "reason": self.message,
            "looks_like": self.looks_like.value,
            "model": self.model,
            "prompt_refs": list(self.prompt_refs),
        }


def build_check_messages(expected: Expected, text: str) -> list[Message]:
    return [
        load_prompt(Role.EXTRACTOR, _PROMPT[expected]).message("system"),
        load_prompt(Role.EXTRACTOR, "check_input").message("user", text=text),
    ]


def refusal_message(
    expected: Expected, looks_like: DocumentKind, source: Source, reason: str
) -> str:
    table = _JOB_MESSAGES if expected == "job_posting" else _RESUME_MESSAGES
    template = table.get(looks_like, _DEFAULT[expected])
    lead = _SOURCE[source]
    first = template.format(source=lead, source_lower=lead[0].lower() + lead[1:])
    return f"{first} {reason}".strip() if reason else first


def _clean_reason(reason: str) -> str:
    text = " ".join(reason.split())[:200].strip()
    if not text or drop_injected_items([text])[1]:
        return ""
    return text if text[-1] in ".!?" else text + "."


async def check_input(
    gateway: ModelGateway, text: str, expected: Expected, source: Source
) -> Refusal | None:
    """None when the input may go on to the extraction, else the Refusal."""
    clean = sanitize_untrusted(text).text[:CHECK_CHARS]
    messages = build_check_messages(expected, clean)
    try:
        done = await gateway.complete(Role.EXTRACTOR, messages, output_type=InputCheck)
    except Exception as exc:  # never block an input because the check failed
        log.warning("input check failed (%s); accepting the %s", type(exc).__name__, expected)
        return None
    check = done.output
    if check.matches or check.looks_like == _EXPECTED_KIND[expected]:
        return None
    reason = _clean_reason(check.reason)
    log.info("input refused: expected %s, looks like %s", expected, check.looks_like.value)
    return Refusal(
        looks_like=check.looks_like,
        message=refusal_message(expected, check.looks_like, source, reason),
        reason=reason,
        model=done.model,
        prompt_refs=done.prompt_refs,
    )
