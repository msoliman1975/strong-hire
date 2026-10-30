/**
 * LB-1 on the v2 Home: the CVs on file, the latest one with its state, and "Add a resume" or
 * "Check a resume". From GET /resumes; deleted CVs are not counted. IN-12: each CV links to its
 * breakdown, with its state and issue counts.
 */
import { Link } from "react-router";

import { useResumes } from "../../api/hooks";
import type { ResumeOut } from "../../api/types";
import { formatDate } from "../../labels";
import { MAX_RESUME_MB, MAX_RESUMES } from "../../limits";
import { resumeCheckPath } from "../../paths";
import { checkedLabel, issueSummary, resumeIssueCounts } from "../onboarding/resumeSummary";

/** The newest CV first. */
export function latestResume(resumes: ResumeOut[]): ResumeOut | null {
  const live = resumes.filter((r) => !r.deleted);
  live.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  return live[0] ?? null;
}

function resumeState(r: ResumeOut): string {
  if (r.status === "pending") return "Being read";
  const counts = resumeIssueCounts(r);
  return [checkedLabel(r), counts && issueSummary(counts)].filter(Boolean).join(" · ");
}

/** The CV's name, linked to its breakdown once it is read. */
function CvName({ r }: { r: ResumeOut }) {
  const name = r.name ?? "Your resume";
  return r.status === "extracted" ? (
    <Link className="home-resumes__name" to={resumeCheckPath(r.id)} aria-label={`Open breakdown for ${name}`}>
      {name}
    </Link>
  ) : (
    <span className="home-resumes__name">{name}</span>
  );
}

export function ResumesCard() {
  const resumes = useResumes();
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const latest = latestResume(resumes.data ?? []);
  const others = live.filter((r) => r.id !== latest?.id);
  const needsCheck = latest !== null && latest.status === "extracted" && !latest.confirmed_at;
  // R3: at the limit, adding means replacing one (delete one on the Resumes page first).
  const addLabel = live.length >= MAX_RESUMES ? "Replace one" : "Add a resume";

  return (
    <section className="card home-journey" data-journey="resumes" aria-labelledby="home-resumes">
      <p className="home-journey__eyebrow">Your resumes</p>
      <h2 id="home-resumes">The resume your interviews are measured against.</h2>
      {resumes.isPending ? (
        <p className="muted">Loading your resumes</p>
      ) : latest === null ? (
        <p className="muted">Add the resume you will interview with. Every match score and plan reads it.</p>
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
                <CvName r={latest} />
                <span className="muted small">
                  {formatDate(latest.uploaded_at)} · {resumeState(latest)}
                </span>
              </dd>
            </div>
          </dl>
          {others.length > 0 && (
            <ul className="plain-list home-resumes__others" aria-label="Your other resumes">
              {others.map((r) => (
                <li key={r.id}>
                  <CvName r={r} /> <span className="muted small">{resumeState(r)}</span>
                </li>
              ))}
            </ul>
          )}
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
                Open breakdown
              </Link>
            )}
          </>
        )}
      </div>
    </section>
  );
}
