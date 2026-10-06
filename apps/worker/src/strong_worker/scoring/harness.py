"""The P8 scorer behind the eval harness interface (strong_evals.interfaces.Scorer).

The harness scores scripted transcripts that have no database rows. Company-mode transcripts
name their profile by company and version in the brief; this adapter finds that profile in the
profiles/ folder (for example profiles/examples/example-corp.json).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from pathlib import Path

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway
from strong_core.profiles import ResolvedProfile, generic_profile, parse_profile
from strong_core.schemas import InterviewerBrief, Scorecard, Turn
from strong_worker.scoring.scorer import ScoringOutcome, SessionScorer


class ProfileNotFoundError(LookupError):
    pass


def find_profile(brief: InterviewerBrief, folder: Path | None = None) -> ResolvedProfile:
    """The profile a brief was planned with: generic mode, or a profile file in `folder`."""
    if brief.generic_mode:
        return generic_profile(company_name=brief.company_name)
    root = folder or get_settings().repo_root / "profiles"
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("company_name") != brief.company_name:
            continue
        profile = parse_profile(data, path)
        if profile.meta.version == brief.profile_version:
            company_id = uuid.uuid5(uuid.NAMESPACE_URL, f"strong-hire/{profile.company_slug}")
            return ResolvedProfile.from_profile(
                profile, company_id=company_id, version=profile.meta.version
            )
    raise ProfileNotFoundError(
        f"No profile file for {brief.company_name} version {brief.profile_version} in {root}"
    )


class HarnessScorer:
    def __init__(self, gateway: ModelGateway, profiles_dir: Path | None = None) -> None:
        self.scorer = SessionScorer(gateway)
        self.profiles_dir = profiles_dir
        self.last: ScoringOutcome | None = None

    async def score(self, brief: InterviewerBrief, turns: Sequence[Turn]) -> Scorecard:
        outcome = await self.scorer.score(brief, turns, find_profile(brief, self.profiles_dir))
        self.last = outcome
        return outcome.scorecard
