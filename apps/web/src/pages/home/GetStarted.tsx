/**
 * R3 explainability on Home: "Get started in 3 steps": add a resume, add a job description, do
 * the first rehearsal. Each step is done from the user's own data (GET /resumes, /job-targets).
 * It shows until all three are done, and then never again; "Hide this" hides it for good. Both
 * are remembered per user in this browser; without storage it simply shows while not done.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { useAuth, useJobs, useResumes } from "../../api/hooks";
import { newJobPath } from "../../paths";

const key = (userId: string) => `sh-getstarted-${userId}`;

function remembered(userId: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key(userId)) ?? null;
  } catch {
    return null;
  }
}

function remember(userId: string, value: "hidden" | "done") {
  try {
    globalThis.localStorage?.setItem(key(userId), value);
  } catch {
    /* storage blocked: the checklist shows again next time, which is harmless */
  }
}

interface Step {
  id: "resume" | "job" | "rehearsal";
  title: string;
  why: string;
  action: { label: string; to: string };
  done: boolean;
}

export function GetStarted() {
  const auth = useAuth();
  const userId = auth.data?.user?.id ?? null;
  const resumes = useResumes();
  const jobs = useJobs();
  const [state, setState] = useState(() => (userId ? remembered(userId) : null));
  const hasResume = resumes.data?.some((r) => !r.deleted) ?? false;
  const hasJob = (jobs.data?.length ?? 0) > 0;
  const hasRehearsal = jobs.data?.some((j) => j.sessions_count > 0) ?? false;
  const allDone = hasResume && hasJob && hasRehearsal;
  // Done once is done for good, even if a resume is deleted later.
  useEffect(() => {
    if (userId && allDone) remember(userId, "done");
  }, [userId, allDone]);

  if (!userId || !resumes.data || !jobs.data) return null;
  if (state === "hidden" || state === "done") return null;

  const steps: Step[] = [
    {
      id: "resume",
      title: "Add your resume",
      why: "We compare it with each job description for your match score and plan.",
      action: { label: "Add a resume", to: "/resumes" },
      done: hasResume,
    },
    {
      id: "job",
      title: "Add the job you're interviewing for",
      why: "Paste the job description. We use it to plan what they'll test.",
      action: { label: "Add a job description", to: newJobPath("rehearsal") },
      done: hasJob,
    },
    {
      id: "rehearsal",
      title: "Do your first rehearsal",
      why: "A mock interview with an AI interviewer, then a debrief with your score.",
      action: { label: "Go to your interviews", to: "/jobs" },
      done: hasRehearsal,
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  if (allDone) return null;
  const current = steps.find((s) => !s.done);

  return (
    <section className="card get-started" aria-labelledby="get-started-heading" data-testid="get-started">
      <div className="get-started__head">
        <h2 id="get-started-heading">Get started in 3 steps</h2>
        <span className="get-started__count">
          {doneCount} of {steps.length} done
        </span>
      </div>
      <div
        className="get-started__track"
        role="progressbar"
        aria-label="Steps done"
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-valuenow={doneCount}
      >
        <div className="get-started__fill" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
      </div>
      <ol className="plain-list get-started__steps">
        {steps.map((s, i) => (
          <li key={s.id} data-done={s.done || undefined} data-current={s === current || undefined}>
            <span className="get-started__mark" aria-hidden="true">
              {s.done ? "✓" : i + 1}
            </span>
            <div>
              <b>{s.title}</b>
              {s.done && <span className="visually-hidden"> (done)</span>}
              {s === current && (
                <>
                  <p className="muted">{s.why}</p>
                  <Link className="btn" to={s.action.to}>
                    {s.action.label}
                  </Link>
                </>
              )}
            </div>
          </li>
        ))}
      </ol>
      <p className="muted small">
        Shown until all 3 are done.{" "}
        <button
          type="button"
          className="text-button"
          onClick={() => {
            remember(userId, "hidden");
            setState("hidden");
          }}
        >
          Hide this
        </button>
      </p>
    </section>
  );
}
