"""Resume comparison logic in code, no model (RC-2 to RC-5)."""

from __future__ import annotations

import uuid
from typing import Any

from strong_api.compare import ranking
from strong_core.schemas import GapAnalysis, JobPosting, Resume, Severity

POSTING = JobPosting.model_validate(
    {
        "company_name": "Stripe",
        "title": "Backend Engineer",
        "role_family": "swe",
        "level": "senior",
        "must_have_skills": ["Go", "Kafka", "Distributed systems"],
        "nice_to_have_skills": [],
        "responsibilities": ["Build payment APIs"],
    }
)


def resume(**extra: Any) -> Resume:
    data: dict[str, Any] = {
        "summary": None,
        "roles": [
            {
                "title": "Engineer",
                "company": "Fernhill Payments",
                "achievements": ["Built the payout API in Go"],
                "skills": [],
            }
        ],
        "skills": ["Go"],
    }
    data.update(extra)
    return Resume.model_validate(data)


def analysis(
    score: int, *, gaps: list[dict[str, Any]] | None = None, reqs: Any = ()
) -> GapAnalysis:
    return GapAnalysis.model_validate(
        {
            "match_score": score,
            "requirement_breakdown": [
                {"requirement": r, "kind": "must_have", "score": s, "evidence": e}
                for r, s, e in reqs
            ],
            "gaps": gaps or [],
            "session_plan": [
                {
                    "priority": 1,
                    "interview_type": "behavioral",
                    "focus_topics": ["Ownership"],
                    "reason": "First.",
                }
            ],
        }
    )


def candidate(name: str, a: GapAnalysis | None, r: Resume | None = None, main: bool = False):
    c = ranking.Candidate(
        resume_id=uuid.uuid4(), name=name, is_main=main, resume=r or resume(), analysis=a
    )
    ranking.prescreen(c, POSTING)
    return c


def test_rc2_prescreen_counts_must_haves_with_the_resume_check_rule() -> None:
    """RC-2: the must-have count needs no model: the IN-12 rule over skills and lines."""
    c = candidate("Platform", None, resume(skills=["Go", "Kafka"]))
    assert (c.must_total, c.must_shown, c.must_missing) == (3, 2, ["Distributed systems"])


def test_rc3_rank_by_score_then_must_haves_then_high_gaps() -> None:
    """RC-3: match score first; a tie goes to the resume with fewer missing must-haves, then
    fewer high-severity gaps. Resumes without a finished analysis are not ranked."""
    high = [{"summary": "No leadership", "severity": "high"}]
    a = candidate("A", analysis(70), resume(skills=["Go"]))
    b = candidate("B", analysis(70), resume(skills=["Go", "Kafka"]))
    c = candidate("C", analysis(80, gaps=high))
    d = candidate("D", analysis(80))
    pending = candidate("E", None)
    order = ranking.ranked([a, b, c, d, pending])
    assert [x.name for x in order] == ["D", "C", "B", "A"]


def test_rc3_reason_names_scores_and_must_haves_only_the_winner_shows() -> None:
    """RC-3: the reason is built from the data, no model call."""
    best = candidate("Platform", analysis(78), resume(skills=["Go", "Kafka"]))
    other = candidate("Generalist", analysis(61), resume(skills=["Python"], roles=[]))
    third = candidate("Startup", analysis(50), resume(skills=["Kafka"], roles=[]))
    text = ranking.reason(ranking.ranked([other, best]))
    assert text is not None
    assert text.startswith("Platform fits best: match 78, against Generalist 61.")
    assert "It shows 2 of 3 must-haves." in text
    assert "Only this resume shows Go and Kafka." in text
    # With a third resume that shows Kafka, only Go is unique to the winner.
    text = ranking.reason(ranking.ranked([other, best, third]))
    assert text is not None and "Only this resume shows Go." in text


def test_rc4_a_gap_another_resume_covers_names_it_and_its_line() -> None:
    """RC-4: covered means rated meets or exceeds with evidence; the line is that resume's line,
    unchanged, and a skill the focus resume lacks can be added."""
    gap = {"summary": "Kafka is not shown", "severity": "medium", "related_requirement": "Kafka"}
    focus = candidate("Platform", analysis(78, gaps=[gap], reqs=[("Kafka", 35, None)]))
    other = candidate(
        "Generalist",
        analysis(61, reqs=[("Kafka", 70, "Kafka")]),
        resume(skills=["Python", "Kafka"]),
    )
    [hint] = ranking.hints(focus, [other])
    assert hint.source is not None
    assert hint.source.resume_name == "Generalist"
    assert (hint.source.line, hint.source.place, hint.source.can_add) == ("Kafka", "skills", True)
    assert focus.resume is not None
    added = ranking.add_line(focus.resume, hint.source)
    assert added.skills == ["Go", "Kafka"]
    assert not ranking.can_add(added, "Kafka", "skills", None)  # now it is there


def test_rc4_an_achievement_goes_to_the_role_at_the_same_company() -> None:
    """RC-4: an achievement can be copied only when the focus resume lists the same company."""
    line = "Ran the Kafka event pipeline for 40 services"
    gap = {"summary": "Event systems", "severity": "high", "related_requirement": "Distributed"}
    reqs = [("Distributed", 100, "Ran the Kafka event pipeline for 40 services")]
    other_resume = resume(
        roles=[
            {"title": "SRE", "company": "Fernhill Payments", "achievements": [line], "skills": []},
            {"title": "Dev", "company": "Elsewhere Inc", "achievements": ["x"], "skills": []},
        ]
    )
    focus = candidate("Platform", analysis(80, gaps=[gap]))
    other = candidate("Ops", analysis(60, reqs=reqs), other_resume)
    [hint] = ranking.hints(focus, [other])
    assert hint.source is not None
    assert (hint.source.place, hint.source.company, hint.source.can_add) == (
        "achievement",
        "Fernhill Payments",
        True,
    )
    assert focus.resume is not None
    added = ranking.add_line(focus.resume, hint.source)
    assert added.roles[0].achievements == ["Built the payout API in Go", line]

    # At a company the focus resume does not list, the hint names the line but cannot add it.
    moved = other_resume.model_copy(
        update={"roles": [other_resume.roles[0].model_copy(update={"company": "Acme"})]}
    )
    other_elsewhere = candidate("Ops", analysis(60, reqs=reqs), moved)
    [hint] = ranking.hints(focus, [other_elsewhere])
    assert hint.source is not None and hint.source.can_add is False


def test_rc4_hints_are_listed_most_severe_first_with_stable_keys() -> None:
    gaps = [
        {"summary": "Low one", "severity": "low"},
        {"summary": "High one", "severity": "high"},
        {"summary": "Medium one", "severity": "medium"},
    ]
    focus = candidate("Platform", analysis(80, gaps=gaps))
    first = ranking.hints(focus, [])
    assert [h.severity for h in first] == [Severity.HIGH, Severity.MEDIUM, Severity.LOW]
    assert [h.key for h in first] == [h.key for h in ranking.hints(focus, [])]


def test_rc5_a_gap_no_resume_covers_has_no_source() -> None:
    """RC-5: weak or unsupported ratings elsewhere do not cover a gap; the web offers Craft a
    story for it instead."""
    gap = {"summary": "Payments", "severity": "high", "related_requirement": "Payments"}
    focus = candidate("Platform", analysis(80, gaps=[gap]))
    weak = candidate("Generalist", analysis(60, reqs=[("Payments", 35, "payments")]))
    no_evidence = candidate("Other", analysis(55, reqs=[("Payments", 70, None)]))
    [hint] = ranking.hints(focus, [weak, no_evidence])
    assert hint.source is None


def test_rc4_a_line_the_focus_resume_already_has_is_marked_not_offered() -> None:
    """RC-4: after Add to resume and Compare again, the analysis may still list the gap. The
    line is then already in the focus resume: say so, and do not offer to add it again."""
    gap = {"summary": "Kafka is not shown", "severity": "medium", "related_requirement": "Kafka"}
    focus = candidate(
        "Platform",
        analysis(78, gaps=[gap], reqs=[("Kafka", 35, None)]),
        resume(skills=["Go", "Kafka"]),
    )
    other = candidate(
        "Generalist", analysis(61, reqs=[("Kafka", 70, "Kafka")]), resume(skills=["Kafka"])
    )
    [hint] = ranking.hints(focus, [other])
    assert hint.source is not None
    assert hint.source.in_resume is True and hint.source.can_add is False


def test_rc5_an_uncovered_gap_names_the_resumes_that_list_it() -> None:
    """RC-5: a gap no resume covers is not "missing" from resumes that list the skill: name
    them, the focus resume first, by the IN-12 rule."""
    gap = {"summary": "No PostgreSQL depth", "severity": "medium", "related_requirement": "Kafka"}
    focus = candidate("Platform", analysis(80, gaps=[gap]), resume(skills=["Go", "Kafka"]))
    other = candidate("Generalist", analysis(60), resume(skills=["Kafka"], roles=[]))
    none = candidate("Startup", analysis(50), resume(skills=["Rust"], roles=[]))
    [hint] = ranking.hints(focus, [other, none])
    assert hint.source is None
    assert hint.listed_in == ["Platform", "Generalist"]
    no_req = {"summary": "Leadership", "severity": "high"}
    [bare] = ranking.hints(candidate("P", analysis(80, gaps=[no_req])), [other])
    assert bare.listed_in == []
