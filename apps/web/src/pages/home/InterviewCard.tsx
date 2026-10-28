import { Link } from "react-router";

import type { JobTargetSummary } from "../../api/types";
import { EXPLAIN, Explain } from "../../components/Explain";
import { CountdownBadge } from "../../components/ui";
import type { PlanView } from "../plan/api";
import { planPath } from "../plan/paths";
import { atBar, MIN_SESSIONS, scored, useJobReadiness } from "../plan/ReadinessApi";
import { ReadinessNotice } from "../plan/ReadinessNotice";
import { daysUntil, interviewDate, isReady, jobCompany, jobRole } from "./interviews";

/**
 * Where an unfinished job setup continues: confirm the posting, then pick a CV, then the gap
 * analysis (which opens the plan page once it has a CV). Display routing only.
 */
export function setupStep(s: JobTargetSummary): string {
  const id = s.job_target.id;
  if (s.job_target.status === "pending") return `/jobs/${id}/confirm`;
  return s.gap_status === null ? `/jobs/${id}/resume` : `/jobs/${id}/gap`;
}

/** What an unfinished setup needs next, in words (the same steps as setupStep). */
export function draftNext(s: JobTargetSummary): string {
  if (s.job_target.status === "pending") return "Job description added. Next: check the job details.";
  if (s.gap_status === null) return "Job description added. Next: pick the resume you sent them.";
  if (s.gap_status === "running") return "Comparing your resume with the job. Next: your plan.";
  return "Job description and resume added. Next: your plan.";
}

/**
 * PP-3: one interview with company, role, match score and the days left (PP-2), as the block on
 * the canvas Home's journey B card. The title opens the plan page, or the setup step still open.
 */
export function InterviewCard({
  summary,
  entry,
  today,
  action = false,
}: {
  summary: JobTargetSummary;
  /** The interview's plan page, when Home loaded it (PP-2 date, and the link). */
  entry?: { resumeId: string; plan: Pick<PlanView, "interview_date" | "days_left"> };
  today?: Date;
  /** The Interviews page gives each card its own primary button; Home has one for the focus. */
  action?: boolean;
}) {
  const plan = entry?.plan;
  const job = summary.job_target;
  const date = plan?.interview_date ?? interviewDate(summary);
  const days = plan?.days_left ?? (date !== null ? daysUntil(date, today) : null);
  const ready = isReady(summary);
  // A ready job without a loaded plan opens it through the gap route, which redirects to the plan.
  const to = !ready ? setupStep(summary) : entry ? planPath(job.id, entry.resumeId) : `/jobs/${job.id}/gap`;
  // R3: on the Interviews page an unfinished setup is a draft that says what comes next.
  if (action && !ready) {
    return (
      <li className="home-interview home-interview--draft" data-testid="interview-card" data-draft="true">
        <h3>
          Draft · {jobRole(summary)} · {jobCompany(summary)}
        </h3>
        <p className="muted small">{draftNext(summary)}</p>
        <div className="home-interview__actions">
          <Link className="btn btn--secondary" to={to}>
            Continue setup →
          </Link>
        </div>
      </li>
    );
  }
  return (
    <li className="home-interview" data-testid="interview-card">
      <div className="home-interview__top">
        <h3>
          <Link to={to}>
            {jobRole(summary)} · {jobCompany(summary)}
          </Link>
        </h3>
        {days !== null ? <CountdownBadge days={days} /> : <span className="muted small">No interview date yet</span>}
      </div>
      <p className="home-interview__match">
        {summary.match_score !== null ? (
          <>
            Match <b>{summary.match_score}</b>
            <span className="muted">/100</span>
          </>
        ) : (
          <span className="muted">No match score yet</span>
        )}
        <span className="muted">
          {" · "}
          {summary.sessions_count} {summary.sessions_count === 1 ? "session" : "sessions"}
        </span>
        {/* GA-1: the gap analysis behind the match score, one click away (v2 gap report). */}
        {summary.match_score !== null && (
          <>
            {" · "}
            <Link className="text-link" to={`/jobs/${job.id}/gap-report`}>
              View gap report
            </Link>
          </>
        )}
      </p>
      {ready && <ReadinessMeter jobId={job.id} />}
      {action ? (
        <div className="home-interview__actions">
          <Link className="btn" to={to}>
            {ready ? "Open the plan" : "Get ready to rehearse"}
          </Link>
        </div>
      ) : (
        !ready && (
          <p className="small">
            <Link className="text-link" to={to}>
              Get ready to rehearse
            </Link>
          </p>
        )
      )}
    </li>
  );
}

/**
 * RD-1 on the interview block: the share of tested skills at the bar, as a bar with the count in
 * text. The API has no single readiness percent, so the bar is that share. RD-3: with the notice.
 */
function ReadinessMeter({ jobId }: { jobId: string }) {
  const readiness = useJobReadiness(jobId);
  if (!readiness.data) return null;
  const r = readiness.data;
  const total = r.skills.length;
  const any = scored(r) > 0;
  const done = atBar(r);
  return (
    <div className="home-readiness" data-testid="readiness-badge">
      {any && total > 0 ? (
        <div className="home-readiness__row">
          <span className="home-readiness__track" aria-hidden="true">
            <span className="home-readiness__fill" style={{ width: `${(done / total) * 100}%` }} />
          </span>
          <span className="home-readiness__text">
            {done} of {total} skills at the bar
          </span>
        </div>
      ) : (
        <p className="small muted">Readiness after {MIN_SESSIONS} Realistic rehearsals</p>
      )}
      <span className="explain-head">
        <ReadinessNotice short />
        <Explain topic="Readiness">{EXPLAIN.readiness}</Explain>
      </span>
    </div>
  );
}
