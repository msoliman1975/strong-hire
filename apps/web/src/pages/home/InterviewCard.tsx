import { Link } from "react-router";

import type { JobTargetSummary } from "../../api/types";
import { CountdownBadge } from "../../components/ui";
import { ReadinessBadge } from "../plan/ReadinessBadge";
import { daysUntil, interviewDate, isReady, jobCompany, jobRole } from "./interviews";

/** Where an unfinished job setup continues. Display routing only. */
function setupStep(s: JobTargetSummary): string {
  return s.job_target.status === "pending" ? `/jobs/${s.job_target.id}/confirm` : `/jobs/${s.job_target.id}/gap`;
}

/** PP-3: one interview with company, role, match score and the days left. */
export function InterviewCard({ summary, today }: { summary: JobTargetSummary; today?: Date }) {
  const job = summary.job_target;
  const date = interviewDate(summary);
  const ready = isReady(summary);
  return (
    <li className="card card--soft home-interview" data-testid="interview-card">
      <div className="home-interview__top">
        <h3>
          {jobRole(summary)} · {jobCompany(summary)}
        </h3>
        {date !== null ? (
          <CountdownBadge days={daysUntil(date, today)} />
        ) : (
          <span className="muted small">No interview date yet</span>
        )}
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
      {ready && <ReadinessBadge jobId={job.id} />}
      <div className="home-interview__actions">
        {ready ? (
          <Link className="btn btn--ink" to={`/jobs/${job.id}/resume`}>
            Continue prep
          </Link>
        ) : (
          <Link className="btn btn--secondary" to={setupStep(summary)}>
            Get ready to rehearse
          </Link>
        )}
        <Link className="text-link" to={`/reports?job=${encodeURIComponent(job.id)}`}>
          Reports
        </Link>
      </div>
    </li>
  );
}
