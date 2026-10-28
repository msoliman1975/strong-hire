/**
 * PP-1: the interview plan page for one job and CV pair (canvas board B1 Plan). With
 * `v2_enabled` on it replaces the gap analysis, rehearsals (PR-3) and session setup pages:
 * header with the countdown (PP-2), what they'll test, where they'll probe, earlier rehearsals
 * and the next rehearsal setup (PP-4).
 */
import { useState } from "react";
import { Link, useParams } from "react-router";

import type { ReportItem } from "../../api/types";
import { CV_DELETED, ReportList } from "../../components/ReportList";
import { Bar, ErrorNotice, Loading, PageHead, StatusBadge } from "../../components/ui";
import { competencyLabel, formatDate, interviewTypeLabel } from "../../labels";
import { contextPath } from "../../paths";
import { usePlan, type PlanView } from "./api";
import { InterviewDate } from "./InterviewDate";
import { YourPlan } from "./YourPlan";
import { StoryFitTable } from "./StoryFitTable";
import { ReadinessPanel, ReadinessRing } from "./ReadinessPanel";
import "./plan.css";

const isVerdict = (r: ReportItem) => r.type === "interview_debrief" && r.hire_signal !== null;

export function PlanPage() {
  const { jobId = "", resumeId = "" } = useParams();
  const plan = usePlan(jobId, resumeId);
  if (plan.isPending) return <Loading label="Loading your interview plan" />;
  if (plan.isError) return <ErrorNotice error={plan.error} />;
  return <PlanBody plan={plan.data} jobId={jobId} resumeId={resumeId} />;
}

function PlanBody({ plan, jobId, resumeId }: { plan: PlanView; jobId: string; resumeId: string }) {
  const posting = plan.job.posting;
  const company = plan.company_name ?? posting?.company_name ?? null;
  const title = posting ? `${posting.title}${company ? ` · ${company}` : ""}` : (plan.job.name ?? "Your interview");
  const cvName = plan.resume.deleted ? CV_DELETED : (plan.resume.name ?? "your CV");
  const gap = plan.gap;
  const analysis = gap?.status === "ready" ? gap.analysis : null;
  const verdicts = plan.reports.filter(isVerdict);
  // The rounds in the company's loop show; a generic plan shows the behavioral round. The other
  // rounds open on request, so the card stays as short as the canvas's.
  const [allTypes, setAllTypes] = useState(false);
  const inLoop = plan.tested.filter((t) => t.in_loop);
  const firstTypes = inLoop.length > 0 ? inLoop : plan.tested.filter((t) => t.interview_type === "behavioral");
  const shownTypes = allTypes || firstTypes.length === 0 ? plan.tested : firstTypes;
  const hiddenTypes = plan.tested.length - shownTypes.length;

  return (
    <div className="plan-page">
      <PageHead title={title} eyebrow="Interview prep" eyebrowTone="prep">
        <p className="muted">
          With {cvName}.{" "}
          {plan.company_mode === "curated"
            ? `Company profile and job details loaded.`
            : "No curated profile for this company yet, so the plan uses a general tech interview style."}
        </p>
        <InterviewDate
          jobId={jobId}
          resumeId={resumeId}
          date={plan.interview_date}
          daysLeft={plan.days_left}
          editable={!plan.job.deleted}
        />
        <ReadinessRing jobId={jobId} resumeId={resumeId} />
      </PageHead>

      <div className="plan-grid">
        <div className="plan-main stack">
          <div className="plan-pair">
            <section className="card" aria-labelledby="plan-test-heading">
              <h2 id="plan-test-heading">What they'll test</h2>
              <p className="muted">
                {plan.company_mode === "curated"
                  ? `From ${company ?? "the company"}'s interview profile${plan.values_framework ? ` and its ${plan.values_framework}` : ""}.`
                  : "Equal weights for each competency, until this company has a profile."}
              </p>
              <div className="plan-tested">
                {shownTypes.map((t) => (
                  <div key={t.interview_type} className="plan-tested__type" data-testid="tested-type">
                    <h3>
                      {interviewTypeLabel[t.interview_type]}{" "}
                      {t.in_loop && <StatusBadge tone="prep">In their loop</StatusBadge>}
                    </h3>
                    <ul className="plain-list">
                      {t.competencies.map((c) => {
                        const pct = Math.round(c.share * 100);
                        return (
                          <li key={c.competency} className="plan-weight">
                            <span>{competencyLabel(c.competency)}</span>
                            <Bar value={pct} label={`${competencyLabel(c.competency)}: ${pct}% of this round`} />
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
              {hiddenTypes > 0 && (
                <button className="btn btn--quiet plan-tested__more" type="button" onClick={() => setAllTypes(true)}>
                  Show the other {hiddenTypes === 1 ? "round" : `${hiddenTypes} rounds`}
                </button>
              )}
            </section>

            <section className="card" aria-labelledby="plan-probe-heading">
              <div className="plan-probe__head">
                <h2 id="plan-probe-heading">Where they'll probe</h2>
                {analysis && (
                  <span className="plan-probe__badge" data-testid="plan-match">
                    Match {analysis.match_score}
                  </span>
                )}
              </div>
              {analysis ? (
                <>
                  {/* A short summary: the top 3, one line each. The full report has the rest. */}
                  <ul className="plan-probe__list" data-testid="probe-areas">
                    {analysis.probe_areas.slice(0, 3).map((p) => (
                      <li key={p} title={p}>
                        {p}
                      </li>
                    ))}
                  </ul>
                  <p className="muted small">
                    From the gap analysis on {formatDate(gap!.created_at)}.
                    {gap!.stale && " The job, your CV or the company profile changed since; run it again to update it."}
                  </p>
                  <Link className="btn btn--secondary" to={`/jobs/${jobId}/gap-report?report=${encodeURIComponent(gap!.id)}`}>
                    Show full report
                  </Link>
                </>
              ) : gap?.status === "running" ? (
                <Loading label="Comparing your resume with the job. This takes about a minute." />
              ) : (
                <div data-testid="no-gap">
                  <p>
                    {gap?.status === "failed"
                      ? (gap.error ?? "The gap analysis failed.")
                      : "Run the free gap analysis to see where they'll probe and what to practice first."}
                  </p>
                  {!plan.job.deleted && !plan.resume.deleted && (
                    <Link className="btn btn--secondary" to={contextPath(jobId, resumeId)}>
                      {gap ? "Run the gap analysis again" : "Run the gap analysis"}
                    </Link>
                  )}
                </div>
              )}
            </section>
          </div>

          <StoryFitTable jobId={jobId} resumeId={resumeId} />

          <section className="card" aria-labelledby="plan-earlier-heading">
            <h2 id="plan-earlier-heading">Earlier rehearsals</h2>
            <p className="muted">
              {verdicts.length === 0
                ? "No scored interview yet for this job and CV."
                : `${verdicts.length} scored ${verdicts.length === 1 ? "interview" : "interviews"}. Latest hire signal: ${verdicts[0].hire_signal}.`}
            </p>
            {plan.reports.length > 0 && <ReportList reports={plan.reports} showJob={false} />}
          </section>
        </div>

        <div className="plan-side stack">
          {plan.job.deleted ? (
            <section className="card">
              <p>This job description was deleted, so it cannot be rehearsed again.</p>
            </section>
          ) : (
            // PP-1, PP-4, RD-2: one card, "Your plan": the day plan's steps with the setup inline.
            <YourPlan plan={plan} jobId={jobId} resumeId={resumeId} />
          )}
          {/* RD-1 to RD-3 (S34): practice readiness per skill. */}
          <ReadinessPanel jobId={jobId} resumeId={resumeId} />
        </div>
      </div>
    </div>
  );
}
