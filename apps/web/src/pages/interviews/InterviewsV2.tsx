/**
 * PP-3 (v2): the Interviews page behind the main menu. Every interview, the soonest first, each
 * with one primary button: "Open the plan" when it is ready, else "Get ready to rehearse" (the
 * setup step still open). "Add a job description" starts the job description flow, which ends on the
 * plan page, where "Start rehearsal" begins the interview. The saved job descriptions (LB-2:
 * delete, archive, restore) stay one click away.
 */
import "../home/home.css";

import { useState } from "react";
import { Link } from "react-router";

import { useJobs } from "../../api/hooks";
import type { JobTargetSummary } from "../../api/types";
import { JobLibrary } from "../../components/LibrarySection";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { newJobPath } from "../../paths";
import { InterviewCard } from "../home/InterviewCard";
import { usePlans } from "../home/SkillCoverage";

export function InterviewsV2() {
  const jobs = useJobs();
  const { loaded } = usePlans();
  const [manage, setManage] = useState(false);

  const entryOf = (s: JobTargetSummary) => loaded.find((l) => l.jobId === s.job_target.id);
  // The soonest interview date first, then the ones with no date, newest first.
  const ordered = [...(jobs.data ?? [])].sort((a, b) => {
    const da = entryOf(a)?.plan.days_left;
    const db = entryOf(b)?.plan.days_left;
    const ka = da === null || da === undefined || da < 0 ? Infinity : da;
    const kb = db === null || db === undefined || db < 0 ? Infinity : db;
    return ka !== kb ? ka - kb : b.job_target.created_at.localeCompare(a.job_target.created_at);
  });

  return (
    <div className="interviews-v2 stack">
      <PageHead title="Interviews" eyebrow="Interview prep" eyebrowTone="prep">
        <div className="page-head__row">
          <p className="muted">Each interview has a plan: what they'll test, your stories for it, and the next rehearsal.</p>
          <Link className="btn" to={newJobPath("rehearsal")}>
            Add a job description
          </Link>
        </div>
      </PageHead>

      {jobs.isPending && <Loading label="Loading your interviews" />}
      {jobs.isError && <ErrorNotice error={jobs.error} />}
      {jobs.data &&
        (ordered.length === 0 ? (
          <section className="card stack" aria-label="No interviews yet">
            <p>Add the job description for the interview you have. You get a free match score and a plan for it.</p>
            <div>
              <Link className="btn" to={newJobPath("rehearsal")}>
                Add a job description
              </Link>
            </div>
          </section>
        ) : (
          <ul className="plain-list interviews-v2__list" aria-label="Your interviews">
            {ordered.map((s) => (
              <InterviewCard key={s.job_target.id} summary={s} entry={entryOf(s)} action />
            ))}
          </ul>
        ))}

      <div>
        <button className="btn btn--quiet" type="button" aria-expanded={manage} onClick={() => setManage((m) => !m)}>
          {manage ? "Hide saved job descriptions" : "Manage saved job descriptions"}
        </button>
      </div>
      {manage && <JobLibrary />}
    </div>
  );
}
