"""Careers and values pages for an auto-profile (AP-1).

Pages come only from the job posting's own domain: the posting host, plus its parent domain
when the host is a careers subdomain such as careers.example.com. Postings on a job board
(Greenhouse, Lever, Workday and similar) have no company domain, so they get no pages.

Fetching reuses the posting scraper (PostingFetcher), so every hop passes the same address
checks and size limits. Pages are fetched one at a time with a pause between requests, and the
job stops after a few pages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from strong_worker.inputs.fetch import PostingFetcher, is_paste_only
from strong_worker.inputs.matching import board_token, url_host
from strong_worker.inputs.sanitize import DATA_CLOSE, DATA_OPEN, sanitize_untrusted

CANDIDATE_PATHS = (
    "/careers",
    "/about",
    "/values",
    "/culture",
    "/about-us",
    "/company",
    "/jobs",
)
MAX_PAGES = 3
MAX_FETCHES = 8
FETCH_DELAY_S = 1.0
MAX_PAGE_CHARS = 8_000
CAREERS_SUBDOMAINS = {"careers", "jobs", "work", "join", "apply", "www"}

# Hosts that carry postings for many companies; their pages say nothing about the company.
JOB_BOARD_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workable.com",
    "smartrecruiters.com",
    "indeed.com",
    "glassdoor.com",
    "wellfound.com",
    "ziprecruiter.com",
    "bamboohr.com",
    "recruitee.com",
    "jobvite.com",
    "icims.com",
    "breezy.hr",
    "teamtailor.com",
    "personio.de",
    "personio.com",
    "dice.com",
    "builtin.com",
    "ycombinator.com",
)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class Page:
    url: str
    text: str


@dataclass
class CompanyPages:
    host: str | None
    pages: list[Page] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [p.url for p in self.pages]


def company_host(source_url: str | None) -> str | None:
    """The posting's own domain, or None when the posting is on a job board or LinkedIn."""
    host = url_host(source_url)
    if host is None or source_url is None:
        return None
    if board_token(source_url) is not None or is_paste_only(source_url):
        return None
    if any(host == d or host.endswith("." + d) for d in JOB_BOARD_DOMAINS):
        return None
    return host


def candidate_urls(source_url: str) -> list[str]:
    """Careers and values page URLs on the posting's domain, most useful first."""
    host = company_host(source_url)
    if host is None:
        return []
    scheme = urlparse(source_url).scheme or "https"
    hosts = [host]
    labels = host.split(".")
    if len(labels) >= 3 and labels[0] in CAREERS_SUBDOMAINS:
        hosts.append(".".join(labels[1:]))
    return [f"{scheme}://{h}{path}" for path in CANDIDATE_PATHS for h in hosts]


async def fetch_company_pages(
    fetcher: PostingFetcher,
    source_url: str | None,
    *,
    delay_s: float | None = None,
    sleep: Sleep = asyncio.sleep,
) -> CompanyPages:
    """Fetch up to MAX_PAGES pages and sanitize their text. Pages that fail are skipped."""
    delay_s = FETCH_DELAY_S if delay_s is None else delay_s
    found = CompanyPages(host=company_host(source_url))
    if source_url is None or found.host is None:
        return found
    seen: set[str] = set()
    for fetches, url in enumerate(candidate_urls(source_url)):
        if len(found.pages) >= MAX_PAGES or fetches >= MAX_FETCHES:
            break
        if fetches:
            await sleep(delay_s)
        fetched = await fetcher.fetch(url)
        if fetched.needs_paste or not fetched.text:
            continue
        clean = sanitize_untrusted(fetched.text, max_chars=MAX_PAGE_CHARS)
        if clean.text in seen:  # /about and /about-us often serve the same page
            continue
        seen.add(clean.text)
        found.pages.append(Page(url, clean.text))
        found.flags += [f"{url}: {flag}" for flag in clean.flags]
    return found


def pages_block(pages: list[Page]) -> str:
    """The pages as one block of text for the prompt, each headed by its URL."""
    parts = []
    for page in pages:
        text = page.text.replace(DATA_OPEN, " ").replace(DATA_CLOSE, " ")
        parts.append(f"Page: {page.url}\n{text}")
    return "\n\n---\n\n".join(parts)
