/**
 * LB-1 on the v2 Home: the CVs on file, the latest one with its state, and "Add a resume" or
 * "Check a resume". From GET /resumes; deleted CVs are not counted.
 */
import { Link } from "react-router";

import { useResumes } from "../../api/hooks";
import type { ResumeOut } from "../../api/types";
import { formatDate } from "../../labels";
import { MAX_RESUME_MB, MAX_RESUMES } from "../../limits";
import { resumeCheckPath } from "../../paths";

/** The newest CV first. */
export function latestResume(resumes: ResumeOut[]): ResumeOut | null {
  const live = resumes.filter((r) => !r.deleted);
  live.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  return live[0] ?? null;
}

function resumeState(r: ResumeOut): string {
  if (r.status === "pending") return "Being read";
  return r.confirmed_at ? "Checked" : "Needs a check";
}

export function ResumesCard() {
  const resumes = useResumes();
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const latest = latestResume(resumes.data ?? []);
  const needsCheck = latest !== null && latest.status === "extracted" && !latest.confirmed_at;
  // R3: at the limit, adding means replacing one (delete one on the Resumes page first).
  const addLabel = live.length >= MAX_RESUMES ? "Replace one" : "Add a resume";

  return (
    <section className="card home-journey" data-journey="resumes" aria-labelledby="home-resumes">
      <p className="home-journey__eyebrow">Your resumes</p>
      <h2 id="home-resumes">The CV your interviews are measured against.</h2>
      {resumes.isPending ? (
        <p className="muted">Loading your resumes</p>
      ) : latest === null ? (
        <p className="muted">Add the CV you will interview with. Every match score and plan reads it.</p>
      ) : (
        <>
          <dl className="home-journey__counts home-resumes__counts">
            <div>
              <dt>On file</dt>
              <dd>{live.length}</dd>
            </div>
            <div className="home-resumes__latest">
              <dt>Latest</dt>
              <dd>
                <span className="home-resumes__name">{latest.name ?? "Your CV"}</span>
                <span className="muted small">
                  {formatDate(latest.uploaded_at)} · {resumeState(latest)}
                </span>
              </dd>
            </div>
          </dl>
        </>
      )}
      <p className="muted small home-resumes__limit">
        {live.length} of {MAX_RESUMES} · up to {MAX_RESUME_MB} MB each
      </p>
      <div className="home-journey__actions">
        {needsCheck && latest ? (
          <>
            <Link className="btn btn--ink" to={resumeCheckPath(latest.id)}>
              Check a resume
            </Link>
            <Link className="btn btn--secondary" to="/resumes">
              {addLabel}
            </Link>
          </>
        ) : (
          <>
            <Link className="btn btn--ink" to="/resumes">
              {addLabel}
            </Link>
            {latest && latest.status === "extracted" && (
              <Link className="btn btn--secondary" to={resumeCheckPath(latest.id)}>
                Check a resume
              </Link>
            )}
          </>
        )}
      </div>
    </section>
  );
}
