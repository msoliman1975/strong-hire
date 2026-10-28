import "./home.css";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { keys, useJobs } from "../../api/hooks";
import { debriefApi } from "../../api/scoring";
import type { JobTargetSummary } from "../../api/types";
import { CoachMark, ErrorNotice, Loading, PageHead } from "../../components/ui";
import { difficultyLabel, interviewTypeLabel } from "../../labels";
import { newJobPath } from "../../paths";
import { newCoachPath } from "../coach/paths";
import type { PlanView } from "../plan/api";
import { planPath } from "../plan/paths";
import { useStories, type Story } from "../stories/api";
import { storiesPath } from "../stories/paths";
import { GetStarted } from "./GetStarted";
import { InterviewCard } from "./InterviewCard";
import { ResumesCard } from "./ResumesCard";
import { coachNudge, focusInterview, interviewDate, daysUntil, isReady, type StoryGap } from "./interviews";
import { coverageOf, planSkills, usePlans } from "./SkillCoverage";
import { StoryLibrary } from "./StoryLibrary";

/**
 * The v2 Home (canvas board Home), shown when `v2_enabled` is on: the coach's nudge (PR-2, with
 * the first story gap), the resumes, interviews (PP-3) and stories cards side by side, then the
 * story library and the skill coverage map (ST-4).
 */
export function HomeV2({ today }: { today?: Date }) {
  const jobs = useJobs();
  const stories = useStories();
  const { pending: plansPending, loaded } = usePlans();

  if (jobs.isPending) return <Loading label="Loading your interviews" />;
  if (jobs.isError) return <ErrorNotice error={jobs.error} />;

  const focus = focusOf(jobs.data, loaded, today);
  const entry = focus ? loaded.find((l) => l.jobId === focus.job_target.id) : undefined;
  const plan = entry?.plan ?? null;
  const days = daysLeftOf(focus, plan, today);
  const gap = stories.data && plan ? firstGap(plan, stories.data) : null;

  return (
    <div className="home-v2">
      <PageHead title="Home" hidden />
      <GetStarted />
      {!plansPending && (
        <HomeCoach summary={focus} planLink={entry ? planPath(entry.jobId, entry.resumeId) : null} gap={gap} days={days} today={today} />
      )}
      {/* In the main menu's order: Resumes, Interviews, Stories. */}
      <div className="home-journeys">
        <ResumesCard />
        <JourneyInterviews jobs={jobs.data} focus={focus} loaded={loaded} today={today} />
        <JourneyStories stories={stories.data} />
      </div>
      <StoryLibrary />
    </div>
  );
}

/** A plan page Home loaded, with the job and CV pair it belongs to (usePlans). */
type LoadedPlan = { jobId: string; resumeId: string; plan: PlanView };

/** The interview in focus: the soonest one ahead by the plan's date (PP-2), else focusInterview. */
function focusOf(jobs: JobTargetSummary[], loaded: LoadedPlan[], today?: Date): JobTargetSummary | null {
  const ahead = loaded
    .filter((l) => l.plan.days_left !== null && l.plan.days_left >= 0)
    .sort((a, b) => (a.plan.days_left ?? 0) - (b.plan.days_left ?? 0));
  const soonest = ahead.length > 0 ? jobs.find((s) => s.job_target.id === ahead[0].jobId) : undefined;
  return soonest ?? focusInterview(jobs, today);
}

function daysLeftOf(summary: JobTargetSummary | null, plan: PlanView | null, today?: Date): number | null {
  if (!summary) return null;
  if (plan?.days_left !== undefined && plan.days_left !== null) return plan.days_left;
  const date = interviewDate(summary);
  return date === null ? null : daysUntil(date, today);
}

/** The first skill the plan tests that no story covers, else the first one only Drafts cover. */
export function firstGap(plan: Pick<PlanView, "tested">, stories: Pick<Story, "skills" | "status">[]): StoryGap | null {
  const skills = planSkills(plan);
  const missing = skills.find((s) => coverageOf(s, stories) === "missing");
  if (missing) return { skill: missing, state: "missing" };
  const thin = skills.find((s) => coverageOf(s, stories) === "thin");
  return thin ? { skill: thin, state: "thin" } : null;
}

/**
 * The coach card (canvas board Home): one specific sentence, "Build it with me" for the story gap,
 * "Show my plan", and a box to ask the coach anything.
 */
function HomeCoach({
  summary,
  planLink,
  gap,
  days,
  today,
}: {
  summary: JobTargetSummary | null;
  planLink: string | null;
  gap: StoryGap | null;
  days: number | null;
  today?: Date;
}) {
  const ready = summary !== null && isReady(summary);
  const jobId = summary?.job_target.id ?? "";
  // PR-2 comes with the job progress. A job that is not ready has none to ask for.
  const progress = useQuery({
    queryKey: keys.progress(jobId, false),
    queryFn: () => debriefApi.progress(jobId, false),
    enabled: ready && gap === null,
  });
  if (ready && gap === null && progress.isPending) return null;
  const next = ready ? (progress.data?.next_session ?? null) : null;

  const primary =
    summary === null ? (
      <Link className="btn" to={newJobPath("rehearsal")}>
        Add a job description
      </Link>
    ) : !ready ? (
      <Link className="btn" to={summary.job_target.status === "pending" ? `/jobs/${jobId}/confirm` : `/jobs/${jobId}/gap`}>
        Finish setting up
      </Link>
    ) : gap ? (
      <Link className="btn" to={newCoachPath({ skill: gap.skill, job: jobId })}>
        Build it with me
      </Link>
    ) : (
      <Link className="btn" to={planLink ?? `/jobs/${jobId}/resume`}>
        Start the next rehearsal
      </Link>
    );

  return (
    <section className="card home-coach" aria-label="Your coach" data-testid="home-coach">
      <CoachMark size={48} />
      <div className="home-coach__body">
        <p className="home-coach__label">Your coach</p>
        <p className="home-coach__line">{coachNudge(summary, gap, next, days, today)}</p>
        <div className="home-coach__actions">
          {primary}
          {planLink ? (
            <Link className="btn btn--secondary" to={planLink}>
              Show my plan
            </Link>
          ) : (
            summary === null && (
              <Link className="btn btn--secondary" to={newCoachPath()}>
                Build a story with me
              </Link>
            )
          )}
        </div>
        <AskCoach jobId={ready ? jobId : undefined} />
      </div>
    </section>
  );
}

/** "Ask your coach": the question opens a coach session with it as the first message. */
function AskCoach({ jobId }: { jobId?: string }) {
  const [text, setText] = useState("");
  const navigate = useNavigate();
  return (
    <form
      className="home-ask"
      onSubmit={(e) => {
        e.preventDefault();
        const ask = text.trim();
        if (ask) navigate(newCoachPath({ ask, job: jobId }));
      }}
    >
      <label htmlFor="home-ask" className="visually-hidden">
        Ask your coach
      </label>
      <input
        id="home-ask"
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Ask anything, like “which story should I use for leadership?”"
        maxLength={2000}
      />
      {text.trim() ? (
        <button type="submit" className="home-ask__go" aria-label="Ask">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      ) : (
        <Link className="home-ask__go" to={newCoachPath({ job: jobId, voice: true })} aria-label="Talk instead of typing">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        </Link>
      )}
    </form>
  );
}

/** Journey A on Home: what the studio is, and the library counts. */
function JourneyStories({ stories }: { stories: Story[] | undefined }) {
  const all = stories ?? [];
  const proven = all.filter((s) => s.status === "proven").length;
  return (
    <section className="card home-journey" data-journey="a" aria-labelledby="home-a">
      <p className="home-journey__eyebrow">Build your stories</p>
      <h2 id="home-a">Turn your career into stories that win interviews.</h2>
      <p className="muted">
        Talk with your coach, shape each story, and sharpen it take by take. Works with or without an interview booked.
      </p>
      <dl className="home-journey__counts">
        <div>
          <dt>Stories</dt>
          <dd>{stories ? all.length : "–"}</dd>
        </div>
        <div>
          <dt>Proven</dt>
          <dd data-tone="ok">{stories ? proven : "–"}</dd>
        </div>
        <div>
          {/* The API has Draft and Proven only; every Draft still needs work. */}
          <dt>Need work</dt>
          <dd data-tone="warn">{stories ? all.length - proven : "–"}</dd>
        </div>
      </dl>
      <div className="home-journey__actions">
        <Link className="btn btn--ink" to={storiesPath}>
          Open the studio
        </Link>
      </div>
    </section>
  );
}

/** Journey B on Home (PP-3): every interview, the one in focus first, with its next rehearsal. */
function JourneyInterviews({
  jobs,
  focus,
  loaded,
  today,
}: {
  jobs: JobTargetSummary[];
  focus: JobTargetSummary | null;
  loaded: LoadedPlan[];
  today?: Date;
}) {
  const ordered = focus ? [focus, ...jobs.filter((s) => s !== focus)] : jobs;
  const entryOf = (s: JobTargetSummary) => loaded.find((l) => l.jobId === s.job_target.id);
  const focusEntry = focus ? entryOf(focus) : undefined;
  return (
    <section className="card home-journey" data-journey="b" aria-labelledby="home-b">
      <p className="home-journey__eyebrow">Prep for an interview</p>
      <h2 id="home-b">Get ready for the interview you have.</h2>
      {jobs.length === 0 ? (
        <p className="muted">Add the job description for the interview you have, and get a free match score.</p>
      ) : (
        <ul className="plain-list home-interviews__list" aria-label="Your interviews">
          {ordered.map((s) => (
            <InterviewCard key={s.job_target.id} summary={s} entry={entryOf(s)} today={today} />
          ))}
        </ul>
      )}
      {focus && focusEntry && <NextRehearsal summary={focus} />}
      <div className="home-journey__actions">
        {focus && isReady(focus) && (
          <Link
            className="btn btn--ink"
            to={focusEntry ? planPath(focusEntry.jobId, focusEntry.resumeId) : `/jobs/${focus.job_target.id}/resume`}
          >
            Continue prep
          </Link>
        )}
        <Link className="btn btn--secondary" to={newJobPath("rehearsal")}>
          Add a job description
        </Link>
      </div>
    </section>
  );
}

/** "Next: Behavioral, Realistic." The PR-2 next session of the interview in focus. */
function NextRehearsal({ summary }: { summary: JobTargetSummary }) {
  const jobId = summary.job_target.id;
  const progress = useQuery({
    queryKey: keys.progress(jobId, false),
    queryFn: () => debriefApi.progress(jobId, false),
  });
  const next = progress.data?.next_session;
  if (!next) return null;
  return (
    <p className="muted home-journey__next">
      <b>Next:</b> {interviewTypeLabel[next.interview_type]} rehearsal, {difficultyLabel[next.difficulty]}
      {next.focus_topics.length > 0 ? `, on ${next.focus_topics[0]}` : ""}.
    </p>
  );
}
