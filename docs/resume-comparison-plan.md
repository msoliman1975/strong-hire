# Resume comparison: execution plan (RC-1 to RC-8)

Which of my resumes fits this role best, and what is it missing? The requirements are in
`docs/spec.md`, section "Resume comparison". This file records the decisions behind them and the
order in which the code lands.

## Decisions (Nov 2, 2026)

| Question | Decision |
| --- | --- |
| Where and when | On demand only: a "Compare my resumes" link next to "Measured against" on Add a target role, and the same action on the role page. Never automatic. |
| How many resumes | Every live, read resume, up to the 5-resume limit. Cached pairs are reused. |
| Rate limit | A comparison counts as one gap analysis run (GA-4). A comparison that reuses every pair counts as none. |
| After the pick | The user clicks "Use this one". Gaps another resume covers get "Add to resume" (copies the line unchanged, no model call) and "Dismiss". |
| Gaps no resume covers | "Craft a story" opens a coach session for the role with the gap as the first message. Nothing runs until the click. |
| Saved or not | Saved on the role, marked out of date when the job, a compared resume or the set of resumes changes. Compare again reruns only the changed pairs. |

## How it works

1. **Pre-screen, no model.** For each resume, the API counts the job's must-have skills the
   resume shows, with the same rule as the resume check (IN-12, `_mentions`). The screen shows
   these counts at once, while the analyses run.
2. **Gap analysis per resume.** For each resume the API reuses a ready, non-stale analysis of the
   same job and resume (any purpose), or one still running for the same inputs. Otherwise it
   creates a `gap_analyses` row with `purpose = comparison` and queues the normal worker job
   (`run_gap_analysis`). The worker does not change: a comparison row is computed like any other.
3. **Ranking and explanation in code.** Match score, then fewer must-haves not shown, then fewer
   high-severity gaps. The reason names the scores and the must-haves only the winner shows.
4. **Gap hints in code.** For each gap of the winner, the other resumes' requirement ratings for
   the same requirement are checked. A score of 70 or more (rating 2 or 3, which needs evidence
   found in that resume) covers it. The evidence is matched to that resume's line (a skill or an
   achievement). A skill line can always be added; an achievement line can be added when the
   winner lists the same company.

## Data

- `gap_analyses.purpose` (`role` or `comparison`, default `role`) and `gap_analyses.source_gap_id`
  (the comparison row a role row was copied from).
- `resume_comparisons`: the role, the entries (`schemas.ResumeComparisonEntry`: resume, analysis,
  reused), `new_runs`, the chosen resume, and the dismissed and applied hint keys.
- Every query that reads "the role's analysis" filters `purpose = role`: the role's latest
  analysis, the job list's match score, the plan, the interviewer brief, Custom setup, sessions,
  reports and the hire-signal history. Reading an analysis by id still works for any purpose.

- A role row copied from a comparison row (Use this one, or creating the role after comparing,
  when the gap analysis starts with `reuse_ready`) keeps `source_gap_id`. It made no model call
  and does not count against the rate limit.
- On Add a target role the posting as checked on step 2 is saved before the comparison starts,
  so the resumes are compared against what the user confirmed.

## Token and cost impact

| Case | Model calls | Approximate tokens |
| --- | --- | --- |
| Pre-screen, ranking, reason, hints, Add to resume, Use this one | none | 0 |
| One resume with a fresh analysis | 1 gap analysis (2 with its one retry) | 3k to 5k in, about 1k out |
| Compare 5 resumes, nothing cached | 5 gap analyses | 15k to 25k in, about 5k out |
| Compare again, nothing changed | none | 0 |

At the hosted open-weight prices in the cost model, the worst case is about $0.03 per
comparison. The rate limit, not cost, is the constraint, which is why a comparison counts as one
run.

## Work packages

Each package owns its folders (CLAUDE.md). In this branch they are three commits in order; split
them into three PRs if preferred, core first.

| # | Package | Folders | IDs |
| --- | --- | --- | --- |
| 1 | Core: `GapPurpose`, `ResumeComparisonEntry`, `gap_analyses.purpose` and `source_gap_id`, `resume_comparisons`, migration 0028, schemas | `packages/core`, `schemas/` | RC-6, RC-7, RC-8 (data) |
| 2 | API: `strong_api.compare` (start, read, use, add line, dismiss), `purpose = role` filters, rate limit counting; worker: `latest_ready_gap` filter | `apps/api`, `apps/worker` | RC-1 to RC-8 |
| 3 | Web: the compare panel on Add a target role and the role page, the role page summary, the hint actions | `apps/web` | RC-1 to RC-6, RC-8 |

## API

```
POST /roles/{job_target_id}/resume-comparison             start or compare again (202)
GET  /roles/{job_target_id}/resume-comparison             the latest one; poll while running
POST /resume-comparisons/{id}/use        {resume_id}      RC-6 on the role page
POST /resume-comparisons/{id}/hints/{key}/add             RC-4: copy the line
POST /resume-comparisons/{id}/hints/{key}/dismiss         RC-4: hide the hint
```

Errors: 409 `too_few_resumes` (fewer than 2 read resumes), 409 when the posting is still being
read, 429 `rate_limited` with Retry-After (as gap analysis).
