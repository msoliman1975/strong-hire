import { Link } from "react-router";

import type { JobTargetSummary } from "../../api/types";
import { CountdownBadge } from "../../components/ui";
import type { PlanView } from "../plan/api";
import { planPath } from "../plan/paths";
import { atBar, MIN_SESSIONS, scored, useJobReadiness } from "../plan/ReadinessApi";
import { ReadinessNotice } from "../plan/ReadinessNotice";
import { daysUntil, interviewDate, isReady, jobCompany, jobRole } from "./interviews";

/** Where an unfinished job setup continues. Display routing only. */
function setupStep(s: JobTargetSummary): string {
  return s.job_target.status === "pending" ? `/jobs/${s.job_target.id}/confirm` : `/jobs/${s.job_target.id}/gap`;
}

/**
 * PP-3: one interview with company, role, match score and the days left (PP-2), as the block on
 * the canvas Home's journey B card. The title opens the plan page, or the setup step still open.
 */
export function InterviewCard({
  summary,
  entry,
  today,
}: {
  summary: JobTargetSummary;
  /** The interview's plan page, when Home loaded it (PP-2 date, and the link). */
  entry?: { resumeId: string; plan: Pick<PlanView, "interview_date" | "days_left"> };
  today?: Date;
}) {
  const plan = entry?.plan;
  const job = summary.job_target;
  const date = plan?.interview_date ?? interviewDate(summary);
  const days = plan?.days_left ?? (date !== null ? daysUntil(date, today) : null);
  const ready = isReady(summary);
  const to = !ready ? setupStep(summary) : entry ? planPath(job.id, entry.resumeId) : `/jobs/${job.id}/resume`;
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
      </p>
      {ready ? (
        <ReadinessMeter jobId={job.id} />
      ) : (
        <p className="small">
          <Link className="text-link" to={to}>
            Get ready to rehearse
          </Link>
        </p>
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
      <ReadinessNotice short />
    </div>
  );
}
