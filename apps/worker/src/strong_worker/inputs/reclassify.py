"""Move stored job targets into the wave 1 role families by their title (RF-11, D-10).

    python -m strong_worker.inputs.reclassify [--apply] [--org ID] [--verbose]

Run it once after the role families release, inside the worker container (docs/hosting.md).
Before wave 1 a finance or consulting posting was stored as `other`, an SRE posting as `swe`, an
analyst as `data_ml` and a non-technical program manager as `tpm`. This moves each stored posting
whose title clearly names a wave 1 family into it. It makes no model calls.

The rule is conservative. A title moves only when one wave 1 family's title keyword matches and is
longer (more specific) than every keyword of the current family that matches, leaving out generic
words such as "engineer"; a tie stays put.
So "Site Reliability Engineer" moves from swe to infra_security, "Software Engineer, Platform"
stays swe, and "Technical Program Manager" stays tpm while "Program Manager" moves.

Without `--apply` it only prints what it would change (a dry run). Each change rewrites
`job_targets.parsed_json.role_family` and adds an audit_logs row with the action
"job_target.reclassify". Gap reports and interviews made before the run keep their numbers; the
next gap analysis and brief use the new family. Users can still change the family on the check
step. Waitlist entries are not touched: people chose their own field there, and there is no title.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import AuditLog, JobTarget
from strong_core.role_families import ROLE_FAMILIES
from strong_core.schemas import RoleFamily
from strong_worker.inputs.confidence import normalize

log = logging.getLogger(__name__)

ACTOR = "system:role-family-reclassify"
ACTION = "job_target.reclassify"

WAVE_1: tuple[RoleFamily, ...] = (
    RoleFamily.INFRA_SECURITY,
    RoleFamily.DATA_ANALYTICS,
    RoleFamily.ENG_MANAGEMENT,
    RoleFamily.FINANCE,
    RoleFamily.CONSULTING_STRATEGY,
    RoleFamily.PROJECT_PROGRAM,
)
"""The families a stored posting can move into."""

SOURCES: frozenset[RoleFamily] = frozenset(
    {RoleFamily.SWE, RoleFamily.DATA_ML, RoleFamily.TPM, RoleFamily.OTHER}
)
"""The families wave 1 split or that held the new roles before it (D-1 to D-3)."""

GENERIC_KEYWORDS: frozenset[str] = frozenset({"engineer", "developer"})
"""Words that name no family on their own, so they never keep a posting in its current family:
"Site Reliability Engineer" and "DevOps Engineer" move to infra_security."""


def _best_match(family: RoleFamily, title: str, *, skip_generic: bool = False) -> int:
    """Length of the longest title keyword of `family` found in the normalized title, else 0."""
    hits = [
        len(k)
        for k in ROLE_FAMILIES[family].title_keywords
        if normalize(k) in title and not (skip_generic and k in GENERIC_KEYWORDS)
    ]
    return max(hits, default=0)


def proposed_family(title: str, current: RoleFamily) -> RoleFamily | None:
    """The wave 1 family this title clearly belongs to, or None to leave it as it is."""
    if current not in SOURCES or not title.strip():
        return None
    norm = normalize(title)
    scores = {f: _best_match(f, norm) for f in WAVE_1}
    best = max(scores.values())
    if best == 0:
        return None
    winners = [f for f, s in scores.items() if s == best]
    if len(winners) != 1:
        return None  # two wave 1 families match equally: leave it for the user
    if _best_match(current, norm, skip_generic=True) >= best:
        return None  # the current family is at least as specific
    return winners[0]


@dataclass
class ReclassifySummary:
    outcomes: Counter[str] = field(default_factory=Counter)
    moves: Counter[str] = field(default_factory=Counter)
    details: list[dict[str, Any]] = field(default_factory=list)

    def format(self) -> str:
        lines = [f"{name}: {count}" for name, count in sorted(self.outcomes.items())]
        lines += [f"  {move}: {count}" for move, count in sorted(self.moves.items())]
        return "\n".join(lines) or "no job targets to check"


async def reclassify_job_targets(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    apply: bool = False,
    org_id: uuid.UUID | None = None,
) -> ReclassifySummary:
    """Check every stored, parsed job target. Writes only when `apply` is True."""
    summary = ReclassifySummary()
    async with sessionmaker() as db:
        query = select(JobTarget).where(JobTarget.parsed_json.is_not(None))
        if org_id is not None:
            query = query.where(JobTarget.org_id == org_id)
        for row in (await db.scalars(query.order_by(JobTarget.created_at))).all():
            if not row.parsed_json:  # still being read (JSON null counts too)
                continue
            parsed = dict(row.parsed_json)
            try:
                current = RoleFamily(parsed.get("role_family", RoleFamily.OTHER.value))
            except ValueError:
                summary.outcomes["skipped_unknown_family"] += 1
                continue
            target = proposed_family(str(parsed.get("title") or ""), current)
            if target is None:
                summary.outcomes["unchanged"] += 1
                continue
            move = f"{current.value} -> {target.value}"
            detail = {"job_target_id": str(row.id), "title": parsed.get("title"), "move": move}
            summary.details.append(detail)
            summary.moves[move] += 1
            if not apply:
                summary.outcomes["would_move"] += 1
                continue
            parsed["role_family"] = target.value
            row.parsed_json = parsed
            db.add(
                AuditLog(
                    org_id=row.org_id,
                    actor=ACTOR,
                    action=ACTION,
                    entity=f"job_target:{row.id}",
                    details_json={"from": current.value, "to": target.value},
                )
            )
            summary.outcomes["moved"] += 1
        if apply:
            await db.commit()
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write the changes (default: dry run)."
    )
    parser.add_argument("--org", type=uuid.UUID, help="Only job targets of this org.")
    parser.add_argument("--verbose", action="store_true", help="Print one line per move.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    summary = asyncio.run(
        reclassify_job_targets(get_sessionmaker(), apply=args.apply, org_id=args.org)
    )
    if args.verbose:
        for item in summary.details:
            print(item)
    print(("" if args.apply else "Dry run, nothing written. ") + "Job targets by outcome:")
    print(summary.format())


if __name__ == "__main__":
    main()
