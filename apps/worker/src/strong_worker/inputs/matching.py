"""Company matching (IN-5): map a posting to one of the curated companies, else generic mode.

Matching uses the company name first (after removing legal suffixes and applying known
aliases), then the posting URL: the company's own career domains, or the board token on
Greenhouse, Lever, Ashby and Workday. Every company name is logged as a company request
(strong_core.companies), so we can see which profiles users ask for.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.companies import normalize_company_name, record_company_request
from strong_core.db.models import Company

log = logging.getLogger(__name__)

# Career-site domains per company slug. A host matches when it equals a domain or ends with
# "." + domain. LinkedIn lists only its careers site: linkedin.com/jobs hosts every company.
COMPANY_DOMAINS: dict[str, tuple[str, ...]] = {
    "google": ("google.com", "careers.google.com"),
    "amazon": ("amazon.jobs", "amazon.com"),
    "microsoft": ("microsoft.com",),
    "meta": ("metacareers.com", "meta.com", "facebook.com"),
    "apple": ("apple.com",),
    "netflix": ("netflix.com", "netflix.net"),
    "nvidia": ("nvidia.com",),
    "salesforce": ("salesforce.com",),
    "uber": ("uber.com",),
    "stripe": ("stripe.com",),
    "openai": ("openai.com",),
    "anthropic": ("anthropic.com",),
    "airbnb": ("airbnb.com",),
    "shopify": ("shopify.com",),
    "linkedin": ("careers.linkedin.com",),
    "oracle": ("oracle.com",),
    "adobe": ("adobe.com",),
    "databricks": ("databricks.com",),
    "snowflake": ("snowflake.com",),
    "atlassian": ("atlassian.com",),
}

# Normalized names that mean a curated company.
NAME_ALIASES: dict[str, str] = {
    "alphabet": "google",
    "google deepmind": "google",
    "deepmind": "google",
    "google cloud": "google",
    "amazon web services": "amazon",
    "aws": "amazon",
    "facebook": "meta",
    "meta platforms": "meta",
    "instagram": "meta",
    "whatsapp": "meta",
    "github": "microsoft",
    "salesforce com": "salesforce",
    "tableau": "salesforce",
    "slack": "salesforce",
}

_WORKDAY_HOST = re.compile(r"^(?P<tenant>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$")
_BOARD_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "jobs.ashbyhq.com",
}


@dataclass(frozen=True)
class CompanyRef:
    id: uuid.UUID
    slug: str
    name: str


@dataclass(frozen=True)
class CompanyMatch:
    company: CompanyRef | None
    method: Literal["name", "domain", "none"]

    @property
    def generic_mode(self) -> bool:
        return self.company is None

    def summary(self) -> dict[str, object]:
        return {
            "company_id": str(self.company.id) if self.company else None,
            "slug": self.company.slug if self.company else None,
            "method": self.method,
            "generic_mode": self.generic_mode,
        }


def url_host(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host.removeprefix("www.") or None


def board_token(url: str | None) -> str | None:
    """The company token in a job board URL, for example 'stripe' in
    boards.greenhouse.io/stripe/jobs/123 or 'nvidia' in nvidia.wd5.myworkdayjobs.com."""
    host = url_host(url)
    if host is None or url is None:
        return None
    if workday := _WORKDAY_HOST.match(host):
        return workday["tenant"]
    if host in _BOARD_HOSTS:
        parts = [p for p in urlparse(url).path.split("/") if p]
        return parts[0].lower() if parts else None
    return None


def match_company(
    companies: Sequence[CompanyRef], company_name: str | None, source_url: str | None
) -> CompanyMatch:
    by_slug = {c.slug: c for c in companies}

    if company_name:
        wanted = normalize_company_name(company_name)
        for company in companies:
            if wanted and wanted in {normalize_company_name(company.name), company.slug}:
                return CompanyMatch(company, "name")
        alias = NAME_ALIASES.get(wanted)
        if alias and alias in by_slug:
            return CompanyMatch(by_slug[alias], "name")

    host = url_host(source_url)
    if host:
        for slug, domains in COMPANY_DOMAINS.items():
            if slug in by_slug and any(host == d or host.endswith("." + d) for d in domains):
                return CompanyMatch(by_slug[slug], "domain")
        token = board_token(source_url)
        if token:
            token = normalize_company_name(token.replace("-", " ")).replace(" ", "")
            if token in by_slug:
                return CompanyMatch(by_slug[token], "domain")

    return CompanyMatch(None, "none")


async def load_companies(db: AsyncSession) -> list[CompanyRef]:
    rows = await db.execute(
        select(Company.id, Company.slug, Company.name).where(Company.active.is_(True))
    )
    return [CompanyRef(id=r.id, slug=r.slug, name=r.name) for r in rows]


async def match_and_log(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_target_id: uuid.UUID,
    company_name: str | None,
    source_url: str | None,
) -> CompanyMatch:
    """Match against the active companies and log the name as a company request.
    The caller commits."""
    found = match_company(await load_companies(db), company_name, source_url)
    host = url_host(source_url)
    if found.generic_mode:
        log.info("unknown company requested: %r (host %s)", company_name, host)
    if company_name and company_name.strip():
        await record_company_request(
            db,
            org_id=org_id,
            user_id=user_id,
            job_target_id=job_target_id,
            company_name=company_name,
            matched_company_id=found.company.id if found.company else None,
            source_host=host,
        )
    return found
