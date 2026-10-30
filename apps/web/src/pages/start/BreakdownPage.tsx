/**
 * ON-4 (mockup #resume-check): the breakdown and the issues on one screen. Edit and each fix open
 * the full editor (the v2 check, IN-12); accept is stored at once. Back and Continue.
 */
import { Link, useParams } from "react-router";

import { useResume, useResumeIssues } from "../../api/hooks";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { resumeCheckPath } from "../../paths";
import { formatSpan, thisMonth } from "../onboarding/resumeChecks";
import { IssueList } from "../resumes/IssueList";
import { PLAN_STYLE, readyPath } from "./paths";

const border = { borderTop: "1px solid var(--sh-line)", paddingTop: 10 };

export function BreakdownPage() {
  const { resumeId = "" } = useParams();
  const record = useResume(resumeId);
  const issues = useResumeIssues(resumeId);
  if (record.isError) return <ErrorNotice error={record.error} />;
  const resume = record.data?.resume;
  if (!resume || !record.data) return <Loading label="Loading your resume" />;
  const today = thisMonth();
  const open = issues.data?.open ?? [];
  return (
    <div className="sx-solo">
      <Link className="sx-small" to={readyPath(resumeId)}>
        Back to what your resume shows
      </Link>
      <div className="sx-stack" style={{ gap: 4 }}>
        <div className="sx-eyebrow">{record.data.name ?? "Your resume"}</div>
        <h1>Breakdown and issues</h1>
        <p className="sx-muted">
          Check what Strova read, and fix or accept each issue. Interviewers and your match scores read this version.
        </p>
      </div>
      <div className="sx-grid2">
        <section className="sx-card" aria-labelledby="bd-heading">
          <div className="sx-between">
            <h2 id="bd-heading">Breakdown</h2>
            <Link className="sx-btn quiet sm" to={resumeCheckPath(resumeId)}>
              Edit
            </Link>
          </div>
          {resume.summary && <p className="sx-small sx-muted">{resume.summary}</p>}
          {resume.roles.map((role, i) => (
            <div key={`${role.company}-${role.title}-${i}`} className="sx-stack" style={{ gap: 2, ...border }}>
              <strong>
                {role.title} · {role.company}
              </strong>
              <span className="sx-small sx-muted">{formatSpan(role.start, role.end, today)}</span>
              {role.achievements
                .filter((a) => a.trim())
                .map((a) => (
                  <span key={a} className="sx-small">
                    · {a}
                  </span>
                ))}
            </div>
          ))}
          {resume.skills.length > 0 && (
            <div className="sx-stack" style={{ gap: 6, ...border }}>
              <strong className="sx-small">Skills</strong>
              <div className="sx-chips">
                {resume.skills.map((s) => (
                  <span key={s} className="sx-chip">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {resume.education.length > 0 && (
            <div className="sx-stack" style={{ gap: 2, ...border }}>
              <strong className="sx-small">Education</strong>
              {resume.education.map((e) => (
                <span key={`${e.institution}-${e.degree ?? ""}`} className="sx-small">
                  {[e.degree && e.field_of_study ? `${e.degree} ${e.field_of_study}` : (e.degree ?? e.field_of_study), e.institution, e.end]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              ))}
            </div>
          )}
        </section>
        <section className="sx-card" aria-labelledby="is-heading">
          <div className="sx-between">
            <h2 id="is-heading">Issues</h2>
            <span className="sx-small sx-muted">
              {issues.data ? `${open.length} open · ${issues.data.accepted.length} accepted` : ""}
            </span>
          </div>
          {issues.isError && <ErrorNotice error={issues.error} />}
          {issues.data && open.length === 0 && <p className="sx-muted sx-small">Nothing to fix. Your resume reads well.</p>}
          <IssueList resumeId={resumeId} issues={open} />
        </section>
      </div>
      <div className="sx-row">
        <Link className="sx-btn" to={PLAN_STYLE}>
          Continue
        </Link>
        <Link className="sx-btn ghost" to={readyPath(resumeId)}>
          Back
        </Link>
      </div>
    </div>
  );
}
