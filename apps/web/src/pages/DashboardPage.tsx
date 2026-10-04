import { Link, useSearchParams } from "react-router";

import { useJobs, useProgress } from "../api/hooks";
import type { JobTargetSummary } from "../api/planned";
import { CompetencyTrends } from "../components/TrendChart";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { formatDate, interviewTypeLabel } from "../labels";
import { setupLink } from "./GapAnalysisPage";

/** Where an unfinished job setup continues. Display routing only. */
function nextSetupStep(s: JobTargetSummary): string | null {
  const { job } = s;
  if (job.status === "extracting" || job.status === "needs_confirmation" || job.status === "failed") {
    return `/jobs/${job.id}/confirm`;
  }
  if (!job.resume_id) return `/jobs/${job.id}/resume`;
  if (s.match_score === null) return `/jobs/${job.id}/gap`;
  return null;
}

export function DashboardPage() {
  const jobs = useJobs();
  const [params] = useSearchParams();

  return (
    <>
      <PageHead title="Your interviews">
        <p>Each job keeps its own gap analysis and history. Trends count Realistic sessions only.</p>
      </PageHead>
      {params.get("upgraded") === "1" && (
        <div className="notice notice--ok" role="status">
          <p>Your plan is active. Your minutes are shown at the top of the page.</p>
        </div>
      )}
      {jobs.isPending && <Loading label="Loading your jobs" />}
      {jobs.isError && <ErrorNotice error={jobs.error} />}
      {jobs.data && jobs.data.length === 0 && (
        <section className="panel" aria-labelledby="empty-heading">
          <h2 id="empty-heading">Add the job you are interviewing for</h2>
          <p>
            Paste the job posting and add your resume. You get a free match score and gap analysis in about five minutes.
          </p>
          <Link className="btn" to="/jobs/new">
            Add your first job
          </Link>
        </section>
      )}
      {jobs.data && jobs.data.length > 0 && (
        <>
          <div className="row row--end">
            <Link className="btn btn--secondary" to="/jobs/new">
              Add another job
            </Link>
          </div>
          <ul className="plain-list section" aria-label="Jobs">
            {jobs.data.map((s) => (
              <JobRow key={s.job.id} summary={s} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function JobRow({ summary }: { summary: JobTargetSummary }) {
  const { job } = summary;
  const setup = nextSetupStep(summary);
  const title = job.posting ? job.posting.title : "Job posting";
  const company = job.posting?.company_name ?? job.source_url ?? "Reading the posting";

  return (
    <li className="job">
      <div>
        <h2>{title}</h2>
        <p className="muted">
          {company}
          {job.company === null && job.posting ? ", general interview style" : ""}
        </p>
        <p>
          {summary.sessions_count} {summary.sessions_count === 1 ? "session" : "sessions"}
          {summary.last_session_at && `, last on ${formatDate(summary.last_session_at)}`}
        </p>
        <div className="row">
          {setup ? (
            <Link className="btn" to={setup}>
              Finish setup
            </Link>
          ) : (
            <NextSessionButton jobId={job.id} />
          )}
          {summary.match_score !== null && (
            <Link className="btn btn--quiet" to={`/jobs/${job.id}/gap`}>
              View gap analysis
            </Link>
          )}
        </div>
      </div>
      <div className="job__score">
        {summary.match_score !== null ? (
          <>
            <p className="score-big">{summary.match_score}</p>
            <p className="muted">match score</p>
          </>
        ) : (
          <p className="muted">No match score yet</p>
        )}
      </div>
      {!setup && <JobTrends jobId={job.id} />}
    </li>
  );
}

function NextSessionButton({ jobId }: { jobId: string }) {
  const progress = useProgress(jobId);
  const next = progress.data?.next_session ?? null;
  return (
    <Link className="btn" to={setupLink(jobId, next)}>
      {next ? `Start next: ${interviewTypeLabel[next.interview_type]}` : "Start a session"}
    </Link>
  );
}

function JobTrends({ jobId }: { jobId: string }) {
  const progress = useProgress(jobId);
  if (progress.isPending) return null;
  if (progress.isError) return <ErrorNotice error={progress.error} />;
  return (
    <section className="job__trends" aria-label="Competency trends">
      {progress.data.snapshots.length === 0 ? (
        <p className="muted">Trends appear here after your first Realistic session.</p>
      ) : (
        <CompetencyTrends snapshots={progress.data.snapshots} />
      )}
    </section>
  );
}
