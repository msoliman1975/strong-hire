"""Input limits the owner approved for v2.0 (Round 3): resume file size, resumes per user, and
job description length. The numbers live here and nowhere else in the API.

The worker checks the word limit on a posting it fetched from a URL. It cannot import this
package, so `strong_worker.inputs.jobs.MAX_POSTING_WORDS` mirrors it and a test checks they match.
"""

from __future__ import annotations

MAX_RESUME_FILE_BYTES = 1024 * 1024
"""IN-3: a resume file over 1 MB gets 413 `file_too_large`."""

MAX_RESUMES_PER_USER = 5
"""IN-3: a user keeps at most 5 saved resumes. Users who already have more keep them."""

MAX_POSTING_WORDS = 2_500
"""IN-1: a job description over 2,500 words gets 422 `posting_too_long`."""

MAX_POSTING_CHARS = 20_000
"""IN-1: a character cap on the posting text, a backstop to the word limit."""

FILE_TOO_LARGE = "file_too_large"
RESUME_LIMIT = "resume_limit"
POSTING_TOO_LONG = "posting_too_long"

FILE_TOO_LARGE_MESSAGE = "The file is larger than 1 MB. Paste the resume text instead."
RESUME_LIMIT_MESSAGE = "You can keep up to 5 resumes. Delete or replace one first."
POSTING_TOO_LONG_MESSAGE = (
    "Job descriptions can be up to 2,500 words. Trim the benefits and company boilerplate."
)


def word_count(text: str) -> int:
    """Words as runs of non-space characters, as the worker counts them."""
    return len(text.split())
