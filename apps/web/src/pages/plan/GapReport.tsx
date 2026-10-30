/**
 * GA-1 to GA-3 as a v2 screen: the full gap report, behind "Show full report" on the plan page
 * and "View gap report" on Interviews. A back link to the plan, then the match score, strengths,
 * gaps, where they'll probe and the practice plan, and the full requirement and competency
 * breakdown below. `?report=<id>` shows one earlier run (R1); otherwise the latest. Uses the
 * existing gap analysis data only.
 */
import "./plan.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { gapApi } from "../../api/gap";
import { keys, useGapAnalysis, useGapReport, useJob } from "../../api/hooks";
import type { GapAnalysis, GapAnalysisOut } from "../../api/types";
import { CV_DELETED } from "../../components/ReportList";
import { Bar, ErrorNotice, Loading, PageHead } from "../../components/ui";
import { competencyLabel, difficultyLabel, formatDate, interviewTypeLabel } from "../../labels";
import { resumeCheckPath } from "../../paths";
import { rolePath } from "../roles/shared";
import { GAP_COPY } from "../../copy";

const SEVERITY: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };

export function GapReport() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const reportId = params.get("report");
  const job = useJob(jobId);
  const latest = useGapAnalysis(jobId);
  const report = useGapReport(reportId);
  const gap = reportId ? report : latest;
  const queryClient = useQueryClient();
  const again = useMutation({
    mutationFn: () => gapApi.start(jobId),
    onSuccess: (result) => {
      queryClient.setQueryData(keys.gap(jobId), result);
      void queryClient.invalidateQueries({ queryKey: keys.jobs });
    },
  });

  const data: GapAnalysisOut | undefined = gap.data;
  const posting = job.data?.posting;
  const role = posting ? `${posting.title} · ${posting.company_name}` : (job.data?.name ?? "Your interview");
  const notStarted = !reportId && gap.error instanceof ApiError && gap.error.status === 404;
  const canRun = !(job.data?.deleted ?? false) && !data?.resume_deleted;
  const plan = data ? rolePath(jobId) : null;

  return (
    <div className="gap-report stack">
      {plan && (
        <p className="gap-report__back">
          <Link className="text-link" to={plan}>
            ← Back to the role
          </Link>
        </p>
      )}
      <PageHead title="Gap report" eyebrow="Interview prep" eyebrowTone="prep">
        <p>{role}</p>
        {data && (
          <p className="muted small">
            Resume:{" "}
            {data.resume_deleted ? (
              CV_DELETED
            ) : (
              <Link to={resumeCheckPath(data.resume_id)} aria-label={`Open breakdown for ${data.resume_name ?? "the resume"}`}>
                {data.resume_name ?? "Resume"}
              </Link>
            )}{" "}
            · {formatDate(data.created_at)}
          </p>
        )}
      </PageHead>

      {reportId && latest.data && latest.data.id !== reportId && (
        <p className="notice" role="status">
          This is an earlier report.{" "}
          <Link to={`/jobs/${jobId}/gap-report?report=${encodeURIComponent(latest.data.id)}`}>See the latest one</Link>.
        </p>
      )}
      {(gap.isPending || data?.status === "running") && (
        <Loading label="Comparing your resume with the job. This takes about a minute." />
      )}
      {notStarted && (
        <div className="card stack">
          <p>There is no gap analysis for this job yet. It is free. Pick the resume you sent them to start it.</p>
          <div>
            <Link className="btn" to={`/jobs/${jobId}/resume`}>
              Pick a resume
            </Link>
          </div>
        </div>
      )}
      {gap.isError && !notStarted && <ErrorNotice error={gap.error} />}
      {again.isError && <ErrorNotice error={again.error} title="The analysis did not start" />}
      {data?.status === "failed" && <ErrorNotice error={data.error ?? "The gap analysis failed."} />}
      {data?.status === "ready" && data.stale && !reportId && (
        <div className="notice" role="status">
          <p>The job, your resume or the company profile changed after this analysis. Run it again to update it.</p>
        </div>
      )}
      {data && (data.status === "failed" || (data.stale && !reportId)) && canRun && (
        <div>
          <button type="button" className="btn btn--secondary" disabled={again.isPending} onClick={() => again.mutate()}>
            Run the analysis again
          </button>
        </div>
      )}
      {data?.status === "ready" && data.analysis && (
        <ReportBody analysis={data.analysis} generic={Boolean(data.generic_mode)} plan={plan} />
      )}
    </div>
  );
}

function ReportBody({ analysis, generic, plan }: { analysis: GapAnalysis; generic: boolean; plan: string | null }) {
  const sessions = [...analysis.session_plan].sort((a, b) => a.priority - b.priority);
  return (
    <>
      <section className="card gap-report__match" aria-labelledby="gap-match-heading">
        <div>
          <h2 id="gap-match-heading">Match score</h2>
          <p className="muted">How well your resume shows what this job asks for.</p>
          {generic && (
            <p className="muted small">
              This company has no curated profile yet, so the analysis uses a general tech interview style.
            </p>
          )}
          <details>
            <summary>How we compute the score</summary>
            <p className="muted small">
              Each requirement and competency gets 0, 35, 70 or 100 points. A score of 70 or more needs a quote from
              your resume. Must-have requirements count twice as much as nice-to-have ones. The match score is 70%
              requirements and 30% competencies.
            </p>
          </details>
        </div>
        <p className="gap-report__score" data-testid="match-score">
          {analysis.match_score}
          <span className="muted">/100</span>
        </p>
      </section>

      <div className="gap-report__pair">
        <section className="card" aria-labelledby="gap-strengths-heading">
          <h2 id="gap-strengths-heading">Strengths</h2>
          <ul className="plain-list gap-report__list">
            {analysis.strengths.map((s) => (
              <li key={s.summary}>
                <b>{s.summary}</b>
                <p className="gap-report__quote">“{s.evidence}”</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="gap-gaps-heading">
          <h2 id="gap-gaps-heading">{GAP_COPY.heading}</h2>
          <p className="muted small">{GAP_COPY.intro}</p>
          <ul className="plain-list gap-report__list">
            {analysis.gaps.map((g) => (
              <li key={g.summary}>
                <span className="gap-report__sev" data-severity={g.severity}>
                  {SEVERITY[g.severity] ?? g.severity}
                </span>{" "}
                <b>{g.summary}</b>
                {g.related_requirement && <p className="muted small">Requirement: {g.related_requirement}</p>}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card" aria-labelledby="gap-probe-heading">
        <h2 id="gap-probe-heading">Where they'll probe</h2>
        <p className="muted">Expect the interviewer to ask more about these.</p>
        <ul className="gap-report__probes">
          {analysis.probe_areas.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="gap-practice-heading">
        <h2 id="gap-practice-heading">Practice plan</h2>
        <p className="muted">The rehearsals this analysis suggests, most useful first. Your plan schedules them.</p>
        <ol className="plain-list gap-report__list">
          {sessions.map((p) => (
            <li key={p.priority}>
              <b>
                {interviewTypeLabel[p.interview_type]}, {difficultyLabel[p.difficulty]}
              </b>
              <p className="muted small">
                {p.focus_topics.join(", ")}. {p.reason}
              </p>
            </li>
          ))}
        </ol>
        {plan && (
          <div className="gap-report__cta">
            <Link className="btn" to={plan}>
              Go to your plan
            </Link>
          </div>
        )}
      </section>

      <details className="card gap-report__more">
        <summary>The full breakdown: every requirement and competency</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Requirement</th>
                <th scope="col">Type</th>
                <th scope="col" className="num">
                  Score
                </th>
                <th scope="col">Evidence from your resume</th>
              </tr>
            </thead>
            <tbody>
              {analysis.requirement_breakdown.map((r) => (
                <tr key={r.requirement}>
                  <td>{r.requirement}</td>
                  <td>{r.kind === "must_have" ? "Must have" : "Nice to have"}</td>
                  <td className="num">{r.score}</td>
                  <td>{r.evidence ?? <span className="muted">No evidence found</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="plain-list gap-report__list">
          {analysis.competency_breakdown.map((c) => (
            <li key={c.competency}>
              <span>
                {competencyLabel(c.competency)} <b>{c.score}</b>
              </span>
              <Bar value={c.score} label={`${competencyLabel(c.competency)}: ${c.score} out of 100`} />
              {c.notes && <p className="muted small">{c.notes}</p>}
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}
