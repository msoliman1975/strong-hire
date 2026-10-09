import { Link, Navigate, useParams } from "react-router";

import { useGapReport, useJob, useReports, useResume } from "../api/hooks";
import type { ReportItem } from "../api/types";
import { CV_DELETED, ReportList } from "../components/ReportList";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { formatDate, severityLabel } from "../labels";
import { contextPath } from "../paths";
import { setupLink } from "./GapAnalysisPage";

const isGap = (r: ReportItem) => r.type === "gap_report";
const isVerdict = (r: ReportItem) => r.type === "interview_debrief" && r.hire_signal !== null;

/**
 * PR-3: one job description and CV pair. Shows the earlier gap reports, findings and hire
 * signals, and starts the next session with this CV. With no gap report yet for the pair, it goes
 * on to the context step, which starts the gap analysis.
 */
export function RehearsalPage() {
  const { jobId = "", resumeId = "" } = useParams();
  const job = useJob(jobId, false);
  const resume = useResume(resumeId, false);
  const reports = useReports({ jobTargetId: jobId, resumeId });
  const latestGap = reports.data?.find(isGap) ?? null;
  const gapReport = useGapReport(latestGap?.id ?? null);

  // A list kept from an earlier visit can be out of date, so the redirect waits for the fresh one.
  const waiting = reports.isPending || job.isPending || (!latestGap && reports.isFetching);
  if (waiting) return <Loading label="Loading your earlier reports" />;
  if (reports.isError) return <ErrorNotice error={reports.error} />;
  if (!latestGap) return <Navigate to={contextPath(jobId, resumeId)} replace />;

  const jobName = job.data?.name ?? "this job";
  const cvName = resume.data?.deleted ? CV_DELETED : (resume.data?.name ?? latestGap.resume_name ?? "your CV");
  const verdicts = reports.data.filter(isVerdict);
  const lastVerdict = verdicts[0] ?? null;
  const analysis = gapReport.data?.analysis ?? null;

  return (
    <>
      <PageHead title={`Rehearse for ${jobName}`}>
        <p>
          With {cvName}. You rehearsed this pair before, so here are your earlier reports, findings and hire signals.
        </p>
      </PageHead>

      <div className="stack">
        <section className="panel" aria-labelledby="pair-heading">
          <h2 id="pair-heading">Where you stand</h2>
          <dl className="dl">
            <dt>Match score</dt>
            <dd>
              {latestGap.match_score ?? "?"} of 100, from the gap analysis on {formatDate(latestGap.at)}
            </dd>
            <dt>Latest hire signal</dt>
            <dd>
              {lastVerdict ? `${lastVerdict.hire_signal}, on ${formatDate(lastVerdict.at)}` : "No scored interview yet"}
            </dd>
            <dt>Scored interviews</dt>
            <dd>{verdicts.length}</dd>
          </dl>
          <div className="row section">
            <Link className="btn" to={setupLink(jobId, null, resumeId)}>
              Start a session
            </Link>
            <Link className="btn btn--secondary" to={`/jobs/${jobId}/gap?report=${encodeURIComponent(latestGap.id)}`}>
              See the gap analysis
            </Link>
            <Link className="btn btn--quiet" to={contextPath(jobId, resumeId)}>
              Run the gap analysis again
            </Link>
            <Link className="btn btn--quiet" to={`/jobs/${jobId}/resume`}>
              Choose another resume
            </Link>
          </div>
        </section>

        {analysis && (
          <div className="grid-2">
            <section className="panel" aria-labelledby="pair-strengths-heading">
              <h2 id="pair-strengths-heading">Strengths</h2>
              <ul className="plain-list">
                {analysis.strengths.slice(0, 3).map((s) => (
                  <li key={s.summary}>{s.summary}</li>
                ))}
              </ul>
            </section>
            <section className="panel" aria-labelledby="pair-gaps-heading">
              <h2 id="pair-gaps-heading">Gaps to work on</h2>
              <ul className="plain-list">
                {analysis.gaps.slice(0, 3).map((g) => (
                  <li key={g.summary}>
                    <span className={`tag tag--${g.severity}`}>{severityLabel[g.severity]} severity</span> {g.summary}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}

        <section className="panel" aria-labelledby="pair-reports-heading">
          <h2 id="pair-reports-heading">Earlier reports for this job and CV</h2>
          <ReportList reports={reports.data} showJob={false} />
        </section>
      </div>
    </>
  );
}
