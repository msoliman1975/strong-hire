/**
 * ST-4: the skill coverage map on Home. The skills come from the user's interviews: the union of
 * the skills their plan pages test. Each skill is covered (a Proven story has its tag), thin
 * (only Draft stories) or missing (no story). Color always comes with the state in text.
 */
import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router";

import { gapApi } from "../../api/gap";
import { keys, useJobs } from "../../api/hooks";
import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import { competencyLabel } from "../../labels";
import { Pill } from "../../components/ui";
import { planApi, planKey, type PlanView } from "../plan/api";
import type { Competency, Story } from "../stories/api";
import { newCoachPath } from "../coach/paths";
import { isReady } from "./interviews";

export type Coverage = "covered" | "thin" | "missing";

export const coverageLabel: Record<Coverage, string> = { covered: "Covered", thin: "Thin", missing: "Missing" };

const PILL_STATE = { covered: "strong", thin: "thin", missing: "gap" } as const;

/**
 * The skills one plan tests: the competencies of the rounds in the company's loop. A generic plan
 * has no loop, so it falls back to the behavioral round, the round stories answer.
 */
export function planSkills(plan: Pick<PlanView, "tested">): Competency[] {
  const inLoop = plan.tested.filter((t) => t.in_loop);
  const rounds = inLoop.length > 0 ? inLoop : plan.tested.filter((t) => t.interview_type === "behavioral");
  return rounds.flatMap((t) => t.competencies.map((c) => c.competency));
}

/** The union of the plans' skills, in first-seen order. No plans: the behavioral skills. */
export function interviewSkills(plans: Pick<PlanView, "tested">[]): Competency[] {
  if (plans.length === 0) return [...COMPETENCIES_BY_TYPE.behavioral];
  return [...new Set(plans.flatMap(planSkills))];
}

export function coverageOf(skill: Competency, stories: Pick<Story, "skills" | "status">[]): Coverage {
  const tagged = stories.filter((s) => s.skills.includes(skill));
  if (tagged.some((s) => s.status === "proven")) return "covered";
  return tagged.length > 0 ? "thin" : "missing";
}

/** Where a missing skill sends the candidate: a coach session for the skill (S31). */
export const missingSkillPath = (skill: Competency) => newCoachPath({ skill });

/** The plan pages of the user's ready interviews: job, then its latest gap analysis's CV, then the plan. */
export function usePlans() {
  const jobs = useJobs();
  const ready = (jobs.data ?? []).filter(isReady).map((s) => s.job_target.id);
  const gaps = useQueries({
    queries: ready.map((jobId) => ({
      queryKey: keys.gap(jobId),
      queryFn: () => gapApi.get(jobId),
      retry: false,
    })),
  });
  const pairs = gaps.flatMap((g, i) => (g.data ? [{ jobId: ready[i], resumeId: g.data.resume_id }] : []));
  const plans = useQueries({
    queries: pairs.map(({ jobId, resumeId }) => ({
      queryKey: planKey(jobId, resumeId),
      queryFn: () => planApi.get(jobId, resumeId),
      retry: false,
    })),
  });
  const pending = jobs.isPending || gaps.some((g) => g.isPending) || plans.some((p) => p.isPending);
  /** Each loaded plan with the job and CV it belongs to. */
  const loaded = plans.flatMap((p, i) => (p.data ? [{ ...pairs[i], plan: p.data }] : []));
  return { pending, plans: loaded.map((l) => l.plan), loaded };
}

export function SkillCoverage({ stories }: { stories: Story[] }) {
  const { pending, plans } = usePlans();
  if (pending) return null;
  const skills = interviewSkills(plans);
  return (
    <section className="card home-coverage" aria-labelledby="home-coverage-heading">
      <div className="home-section__head">
        <h2 id="home-coverage-heading">What your stories prove</h2>
        <p className="muted small">
          {plans.length > 0 ? "Across the skills your interviews test" : "Across the skills behavioral interviews test"}
        </p>
      </div>
      <ul className="plain-list chip-list home-coverage__skills" aria-label="Skill coverage">
        {skills.map((skill) => {
          const state = coverageOf(skill, stories);
          return (
            <li key={skill} data-testid="skill-coverage" data-coverage={state}>
              {state === "missing" ? (
                <Link className="home-coverage__link" to={missingSkillPath(skill)}>
                  <Pill state="gap">
                    {competencyLabel(skill)} <span className="home-coverage__state">{coverageLabel[state]}</span>
                    <span className="visually-hidden">. Build a story for it with the coach</span>
                  </Pill>
                </Link>
              ) : (
                <Pill state={PILL_STATE[state]}>
                  {competencyLabel(skill)} <span className="home-coverage__state">{coverageLabel[state]}</span>
                </Pill>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
