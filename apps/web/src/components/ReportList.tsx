import { Link } from "react-router";

import { reportPath } from "../api/reports";
import type { ReportItem } from "../api/types";
import { formatDate, interviewTypeLabel, modeLabel } from "../labels";

/** Shown where the name of a deleted job description or CV was (R1). */
export const JD_DELETED = "JD deleted";
export const CV_DELETED = "CV deleted";

export const reportTypeLabel: Record<ReportItem["type"], string> = {
  gap_report: "Gap report",
  interview_debrief: "Interview debrief",
};

export const jobLabel = (r: { job_deleted: boolean; job_name: string | null }) =>
  r.job_deleted ? JD_DELETED : (r.job_name ?? "Job");

function summary(r: ReportItem): string {
  if (r.type === "gap_report") {
    const cv = r.resume_deleted ? CV_DELETED : (r.resume_name ?? "CV");
    return `Match score ${r.match_score ?? "?"}. ${cv}`;
  }
  const kind = r.interview_type ? interviewTypeLabel[r.interview_type] : "Interview";
  const mode = r.mode ? `, ${modeLabel[r.mode]}` : "";
  const minutes = r.duration_min ? `, ${r.duration_min} min` : "";
  const result =
    r.status === "ready" ? (r.hire_signal ?? "Ready") : r.status === "failed" ? "Scoring failed" : "Scoring";
  return `${kind}${mode}${minutes}. ${result}`;
}

/** Rows of gap reports and debriefs, newest first as the API sends them. Each opens its page. */
export function ReportList({ reports, showJob = true }: { reports: ReportItem[]; showJob?: boolean }) {
  if (reports.length === 0) return <p className="muted">No reports yet.</p>;
  return (
    <ul className="plain-list" aria-label="Reports">
      {reports.map((r) => (
        <li key={`${r.type}-${r.id}`} className="row row--between">
          <div>
            <Link to={reportPath(r)}>
              <strong>{reportTypeLabel[r.type]}</strong>
              {showJob && <>: {jobLabel(r)}</>}
            </Link>
            <p className="muted">{summary(r)}</p>
          </div>
          <span className="muted">{formatDate(r.at)}</span>
        </li>
      ))}
    </ul>
  );
}
