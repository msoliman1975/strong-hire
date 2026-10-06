import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { useGapAnalysis, useJob } from "../api/hooks";
import type { GapAnalysis, PlannedSession } from "../api/types";
import { Bar, ErrorNotice, Loading, PageHead } from "../components/ui";
import { competencyLabel, difficultyLabel, interviewTypeLabel, severityLabel } from "../labels";

export function setupLink(jobId: string, plan?: PlannedSession | null): string {
  if (!plan) return `/jobs/${jobId}/sessions/new`;
  const q = new URLSearchParams({ type: plan.interview_type, difficulty: plan.difficulty });
  return `/jobs/${jobId}/sessions/new?${q.toString()}`;
}

/** GA-1 to GA-3: match score, breakdown, strengths, gaps, probe areas and the session plan. */
export function GapAnalysisPage() {
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  const gap = useGapAnalysis(jobId);

  const posting = job.data?.posting;
  const title = posting ? `${posting.title} at ${posting.company_name}` : "Gap analysis";
  const notStarted = gap.error instanceof ApiError && gap.error.status === 404;

  return (
    <>
      <PageHead title="Gap analysis">
        <p>{title}</p>
      </PageHead>
      {(gap.isPending || gap.data?.status === "running") && (
        <Loading label="Comparing your resume with the job. This takes about a minute." />
      )}
      {notStarted && (
        <div className="panel">
          <p>There is no gap analysis for this job yet. It is free. Choose a resume to start it.</p>
          <Link className="btn" to={`/jobs/${jobId}/resume`}>
            Choose a resume
          </Link>
        </div>
      )}
      {gap.isError && !notStarted && <ErrorNotice error={gap.error} />}
      {gap.data?.status === "failed" && <ErrorNotice error={gap.data.error ?? "The gap analysis failed."} />}
      {gap.data?.status === "ready" && gap.data.analysis && (
        <AnalysisView jobId={jobId} analysis={gap.data.analysis} />
      )}
    </>
  );
}

function AnalysisView({ jobId, analysis }: { jobId: string; analysis: GapAnalysis }) {
  const first = [...analysis.session_plan].sort((a, b) => a.priority - b.priority)[0];
  return (
    <div className="stack">
      <section className="panel" aria-labelledby="match-heading">
        <div className="row row--between">
          <div>
            <h2 id="match-heading">Match score</h2>
            <p className="muted">How well your resume shows what this job asks for.</p>
          </div>
          <p className="score-big" data-testid="match-score">
            {analysis.match_score}
            <span className="visually-hidden"> out of 100</span>
          </p>
        </div>
        {first && (
          <div className="row">
            <Link className="btn" to={setupLink(jobId, first)}>
              Start the recommended session
            </Link>
            <span className="muted">
              {interviewTypeLabel[first.interview_type]}, {difficultyLabel[first.difficulty]}
            </span>
          </div>
        )}
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="strengths-heading">
          <h2 id="strengths-heading">Strengths</h2>
          <ul className="plain-list">
            {analysis.strengths.map((s) => (
              <li key={s.summary}>
                <strong>{s.summary}</strong>
                <p className="quote">{s.evidence}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel" aria-labelledby="gaps-heading">
          <h2 id="gaps-heading">Gaps</h2>
          <ul className="plain-list">
            {analysis.gaps.map((g) => (
              <li key={g.summary}>
                <span className={`tag tag--${g.severity}`}>{severityLabel[g.severity]} severity</span>{" "}
                <strong>{g.summary}</strong>
                {g.related_requirement && <p className="muted">Requirement: {g.related_requirement}</p>}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel" aria-labelledby="req-heading">
        <h2 id="req-heading">Requirements</h2>
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
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="comp-heading">
          <h2 id="comp-heading">Competencies</h2>
          <ul className="plain-list">
            {analysis.competency_breakdown.map((c) => (
              <li key={c.competency}>
                <div className="row row--between">
                  <span>{competencyLabel(c.competency)}</span>
                  <span>{c.score}</span>
                </div>
                <Bar value={c.score} label={`${competencyLabel(c.competency)}: ${c.score} out of 100`} />
                {c.notes && <p className="muted">{c.notes}</p>}
              </li>
            ))}
          </ul>
        </section>
        <section className="panel" aria-labelledby="probe-heading">
          <h2 id="probe-heading">Likely probe areas</h2>
          <p className="muted">Expect the interviewer to ask more about these.</p>
          <ul>
            {analysis.probe_areas.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel" aria-labelledby="plan-heading">
        <h2 id="plan-heading">Practice plan</h2>
        <ol className="plain-list">
          {[...analysis.session_plan]
            .sort((a, b) => a.priority - b.priority)
            .map((p) => (
              <li key={p.priority} className="row row--between">
                <div>
                  <strong>
                    {interviewTypeLabel[p.interview_type]}, {difficultyLabel[p.difficulty]}
                  </strong>
                  <p className="muted">
                    {p.focus_topics.join(", ")}. {p.reason}
                  </p>
                </div>
                <Link className="btn btn--secondary" to={setupLink(jobId, p)}>
                  Set up this session
                </Link>
              </li>
            ))}
        </ol>
      </section>
    </div>
  );
}
