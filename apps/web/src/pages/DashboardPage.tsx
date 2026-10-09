import { Link, useSearchParams } from "react-router";

import { useJobs, useProgress } from "../api/hooks";
import type { JobTargetSummary } from "../api/types";
import { CompetencySparklines } from "../components/TrendChart";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { difficultyLabel, formatDate, interviewTypeLabel } from "../labels";
import { setupLink } from "./GapAnalysisPage";

/** Where an unfinished job setup continues. Display routing only. */
function nextSetupStep(s: JobTargetSummary): string | null {
  const job = s.job_target;
  if (job.status === "pending") return `/jobs/${job.id}/confirm`;
  if (s.match_score === null) return `/jobs/${job.id}/gap`;
  return null;
}

function jobTitle(s: JobTargetSummary): string {
  const job = s.job_target;
  return job.name ?? (job.posting ? job.posting.title : "Job posting");
}

function jobCompany(s: JobTargetSummary): string {
  const job = s.job_target;
  return job.posting?.company_name ?? job.source_url ?? "Reading the posting";
}

/** The job with the most recent session: its trend fills the side column. */
function latestPracticed(jobs: JobTargetSummary[]): JobTargetSummary | null {
  const practiced = jobs.filter((s) => s.last_session_at !== null && nextSetupStep(s) === null);
  practiced.sort((a, b) => (b.last_session_at ?? "").localeCompare(a.last_session_at ?? ""));
  return practiced[0] ?? null;
}

export function DashboardPage() {
  const jobs = useJobs();
  const [params] = useSearchParams();
  const focus = jobs.data ? latestPracticed(jobs.data) : null;

  return (
    <>
      <PageHead title="Your interviews">
        <div className="page-head__row">
          <p>Each job keeps its own gap analysis and history. Trends count full Realistic sessions only, not mini interviews.</p>
          {jobs.data && jobs.data.length > 0 && (
            <Link className="btn btn--secondary" to="/jobs/new">
              Add another job
            </Link>
          )}
        </div>
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
        <div className="with-side">
          <ul className="plain-list job-list" aria-label="Jobs">
            {jobs.data.map((s) => (
              <JobCard key={s.job_target.id} summary={s} />
            ))}
          </ul>
          {focus && <TrendSide summary={focus} />}
        </div>
      )}
    </>
  );
}

function JobCard({ summary }: { summary: JobTargetSummary }) {
  const job = summary.job_target;
  const setup = nextSetupStep(summary);

  return (
    <li className="job-card">
      <div>
        <h2>{jobTitle(summary)}</h2>
        <p className="muted">
          {jobCompany(summary)}
          {job.generic_mode ? ", general interview style" : ""}
        </p>
      </div>
      <div className="match">
        {summary.match_score !== null ? (
          <>
            <p className="match__value">
              {summary.match_score}
              <small>/100</small>
            </p>
            <p className="match__label">Match</p>
          </>
        ) : (
          <p className="match__label">No match score yet</p>
        )}
      </div>
      <p className="job-card__meta">
        {setup && <span className="chip chip--setup">Setup not finished</span>}
        <span>
          {summary.sessions_count} {summary.sessions_count === 1 ? "session" : "sessions"}
          {summary.last_session_at && `, last on ${formatDate(summary.last_session_at)}`}
        </span>
      </p>
      <div className="job-card__actions">
        {setup ? (
          <Link className="btn btn--secondary" to={setup}>
            Continue setup
          </Link>
        ) : (
          <NextSessionButton jobId={job.id} />
        )}
        {summary.match_score !== null && (
          <Link className="text-link" to={`/jobs/${job.id}/gap`}>
            View gap analysis
          </Link>
        )}
        <Link className="text-link" to={`/reports?job=${encodeURIComponent(job.id)}`}>
          Reports
        </Link>
      </div>
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

/** PR-1 and PR-2 for the most recently practiced job: trend per competency and the next rehearsal. */
function TrendSide({ summary }: { summary: JobTargetSummary }) {
  const jobId = summary.job_target.id;
  const progress = useProgress(jobId);
  if (progress.isPending) return null;
  if (progress.isError) return <ErrorNotice error={progress.error} />;
  const next = progress.data.next_session;

  return (
    <aside className="side-column" aria-label="Your trend">
      <section className="side-panel" aria-labelledby="trend-heading">
        <h2 id="trend-heading">Your trend</h2>
        <p className="muted small">
          {jobTitle(summary)}, {jobCompany(summary)}. Realistic sessions.
        </p>
        {progress.data.snapshots.length === 0 ? (
          <p className="muted small">Trends appear here after your first full Realistic session (30 or 45 minutes).</p>
        ) : (
          <CompetencySparklines snapshots={progress.data.snapshots} />
        )}
      </section>
      {next && (
        <section className="next-card" aria-labelledby="next-side-heading">
          <p className="next-card__tag">Next rehearsal</p>
          <h2 id="next-side-heading">
            {interviewTypeLabel[next.interview_type]}, {difficultyLabel[next.difficulty]}
          </h2>
          {next.focus_topics.length > 0 && <p className="muted small">Focus: {next.focus_topics.join(", ")}</p>}
        </section>
      )}
    </aside>
  );
}
