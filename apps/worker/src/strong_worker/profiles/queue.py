"""Queue the auto-profile job for a generic-mode job target (AP-1).

Kept apart from profiles.jobs so the input jobs can import it without an import cycle.
"""

from __future__ import annotations

import logging
from typing import Any

from strong_core.companies import normalize_company_name
from strong_worker.profiles.pages import company_host

log = logging.getLogger(__name__)

UNUSABLE_NAMES = {"", "unknown", "confidential", "stealth", "stealth startup"}


def usable_name(company_name: str | None) -> str | None:
    """The normalized name, or None when it names no real company."""
    normalized = normalize_company_name(company_name or "")
    return None if normalized in UNUSABLE_NAMES else normalized


async def queue_auto_profile(
    ctx: dict[str, Any], *, company_name: str | None, source_url: str | None, org_id: str
) -> bool:
    """Queue build_auto_profile for a generic-mode job target. Returns True when queued.

    Does nothing without a usable company name or a company domain, or outside a worker (tests
    call the input jobs with no Redis). The Arq job id keeps one queued job per company.
    """
    normalized = usable_name(company_name)
    redis = ctx.get("redis")
    if normalized is None or company_host(source_url) is None or redis is None:
        return False
    try:
        await redis.enqueue_job(
            "build_auto_profile",
            company_name=company_name,
            source_url=source_url,
            org_id=org_id,
            _job_id=f"auto_profile:{normalized}",
        )
    except Exception as exc:  # an auto-profile is optional; never fail the input job
        log.warning("could not queue the auto-profile for %s: %s", normalized, exc)
        return False
    return True
