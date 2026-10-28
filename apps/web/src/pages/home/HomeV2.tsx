import "./home.css";

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { keys, useJobs } from "../../api/hooks";
import { debriefApi } from "../../api/scoring";
import type { JobTargetSummary } from "../../api/types";
import { CoachLine, ErrorNotice, Eyebrow, Loading, PageHead } from "../../components/ui";
import { newJobPath } from "../../paths";
import { InterviewCard } from "./InterviewCard";
import { coachAdvice, focusInterview, isReady } from "./interviews";
import { StoryLibrary } from "./StoryLibrary";

/**
 * The v2 Home (canvas board Home), shown when `v2_enabled` is on: the coach's next-session advice
 * (PR-2), one card per interview (PP-3) and the story library (S21's section).
 */
export function HomeV2({ today }: { today?: Date }) {
  const jobs = useJobs();
  const focus = jobs.data ? focusInterview(jobs.data, today) : null;

  return (
    <div className="home-v2">
      <PageHead title="Home" />
      {jobs.isPending && <Loading label="Loading your interviews" />}
      {jobs.isError && <ErrorNotice error={jobs.error} />}
      {jobs.data && <HomeCoach summary={focus} today={today} />}
      {jobs.data && (
        <section className="card card--prep home-interviews" aria-labelledby="home-interviews-heading">
          <Eyebrow tone="prep">Prep for an interview</Eyebrow>
          <h2 id="home-interviews-heading">Get ready for the interview you have.</h2>
          {jobs.data.length === 0 ? (
            <p className="muted">Add the job description for the interview you have, and get a free match score.</p>
          ) : (
            <ul className="plain-list home-interviews__list" aria-label="Your interviews">
              {jobs.data.map((s) => (
                <InterviewCard key={s.job_target.id} summary={s} today={today} />
              ))}
            </ul>
          )}
          <div>
            <Link className="btn btn--secondary" to={newJobPath("rehearsal")}>
              Add an interview
            </Link>
          </div>
        </section>
      )}
      <StoryLibrary />
    </div>
  );
}

/** PR-2: the next-session advice for the interview in focus, as one sentence from the coach. */
function HomeCoach({ summary, today }: { summary: JobTargetSummary | null; today?: Date }) {
  const ready = summary !== null && isReady(summary);
  const jobId = summary?.job_target.id ?? "";
  // PR-2 comes with the job progress. A job that is not ready has none to ask for.
  const progress = useQuery({
    queryKey: keys.progress(jobId, false),
    queryFn: () => debriefApi.progress(jobId, false),
    enabled: ready,
  });
  if (ready && progress.isPending) return null;
  const next = ready ? (progress.data?.next_session ?? null) : null;
  const action =
    summary === null ? (
      <Link className="btn" to={newJobPath("rehearsal")}>
        Add your interview
      </Link>
    ) : ready ? (
      <Link className="btn" to={`/jobs/${summary.job_target.id}/resume`}>
        Start the next rehearsal
      </Link>
    ) : null;
  return (
    <div data-testid="home-coach">
      <CoachLine actions={action}>{coachAdvice(summary, next, today)}</CoachLine>
    </div>
  );
}
