/**
 * MSW handlers for practice readiness (RD-1) and the day plan (RD-2), with the shapes in
 * openapi.json. Like the API, both are put together from other mocked endpoints: the plan view
 * (tested skills, interview date, gap analysis plan) and the job's progress snapshots. The mock
 * does not weight by recency or check model profiles; the API tests cover those rules.
 */
import { http, HttpResponse } from "msw/http";

import type { Competency, JobProgress, PlannedSession } from "../api/types";
import type { PlanView } from "../pages/plan/api";
import type { DayPlan, DayPlanItem, Readiness } from "../pages/plan/ReadinessApi";
import { MIN_SESSIONS } from "../pages/plan/ReadinessApi";

const API = "*/api";

const today = () => new Date().toISOString().slice(0, 10);

function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function readinessOf(jobId: string, plan: PlanView | null, progress: JobProgress | null): Readiness {
  const tested = plan?.tested.filter((t) => t.in_loop) ?? [];
  const types = tested.length > 0 ? tested : (plan?.tested ?? []);
  const skills = [...new Set(types.flatMap((t) => t.competencies.map((c) => c.competency)))];
  const by = new Map<Competency, number[]>();
  for (const s of progress?.snapshots ?? []) by.set(s.competency, [...(by.get(s.competency) ?? []), s.score]);
  return {
    job_target_id: jobId,
    kind: "practice_estimate",
    as_of: today(),
    skills: skills.map((competency) => {
      const scores = by.get(competency) ?? [];
      if (scores.length < MIN_SESSIONS) {
        return { competency, status: "not_enough_data", score: null, sessions_counted: scores.length };
      }
      const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
      return { competency, status: "scored", score: Math.round(((mean - 1) / 3) * 100), sessions_counted: scores.length };
    }),
  };
}

function rehearsal(p: PlannedSession, mode: DayPlanItem["mode"]): DayPlanItem {
  return {
    kind: "rehearsal",
    interview_type: p.interview_type,
    difficulty: p.difficulty,
    mode,
    focus_topics: p.focus_topics,
    competency: null,
    story_id: null,
    strength: null,
    reason: p.reason,
  };
}

function dayPlanOf(jobId: string, resumeId: string, plan: PlanView | null): DayPlan {
  const sessions = [plan?.next_session, ...[...(plan?.gap?.analysis?.session_plan ?? [])].sort((a, b) => a.priority - b.priority)]
    .filter((p): p is PlannedSession => !!p)
    .filter((p, i, all) => all.findIndex((q) => q.interview_type === p.interview_type && q.difficulty === p.difficulty) === i);
  const list: PlannedSession[] = sessions.length
    ? sessions
    : [{ priority: 1, interview_type: "behavioral", difficulty: "realistic", focus_topics: ["Behavioral practice"], reason: "Start with a behavioral rehearsal." }];
  const tried = new Set<string>();
  let i = 0;
  const next = () => {
    const p = list[i++ % list.length];
    const item = rehearsal(p, tried.has(p.interview_type) ? "realistic" : "coach");
    tried.add(p.interview_type);
    return item;
  };
  const left = plan?.days_left ?? null;
  const base = {
    job_target_id: jobId,
    resume_id: resumeId,
    interview_date: plan?.interview_date ?? null,
    days_left: left,
    days: [],
    days_not_shown: 0,
    next_steps: [],
  };
  if (left === null || left < 0) return { ...base, kind: "next_steps", next_steps: [next(), next(), next()] };
  if (left === 0) {
    return { ...base, kind: "by_day", days: [{ day: today(), items: [{ ...rehearsal(list[0], "coach"), difficulty: "friendly" }] }] };
  }
  const days = Array.from({ length: Math.min(left, 28) }, (_, d) => ({
    day: addDays(today(), d),
    items: [d === left - 1 ? { ...rehearsal(list[0], "realistic"), difficulty: "realistic" as const } : next()],
  }));
  return { ...base, kind: "by_day", days, days_not_shown: Math.max(0, left - 28) };
}

export function readinessHandlers() {
  const read = async <T,>(request: Request, path: string): Promise<T | null> => {
    const base = new URL(request.url).origin + "/api";
    const res = await fetch(`${base}${path}`, { headers: request.headers });
    return res.ok ? ((await res.json()) as T) : null;
  };
  return [
    http.get(`${API}/plan/:jobId/:resumeId/readiness`, async ({ params, request }) => {
      const jobId = String(params.jobId);
      const plan = await read<PlanView>(request, `/plan/${jobId}/${String(params.resumeId)}`);
      if (!plan) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      const progress = await read<JobProgress>(request, `/job-targets/${jobId}/progress`);
      return HttpResponse.json(readinessOf(jobId, plan, progress));
    }),
    http.get(`${API}/readiness/:jobId`, async ({ params, request }) => {
      const jobId = String(params.jobId);
      const progress = await read<JobProgress>(request, `/job-targets/${jobId}/progress`);
      if (!progress) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      const behavioral: Competency[] = ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"];
      const plan = {
        tested: [{ interview_type: "behavioral", in_loop: true, competencies: behavioral.map((competency) => ({ competency, weight: 1, share: 1 / 6 })) }],
      } as PlanView;
      return HttpResponse.json(readinessOf(jobId, plan, progress));
    }),
    http.get(`${API}/plan/:jobId/:resumeId/day-plan`, async ({ params, request }) => {
      const jobId = String(params.jobId);
      const resumeId = String(params.resumeId);
      const plan = await read<PlanView>(request, `/plan/${jobId}/${resumeId}`);
      if (!plan) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      return HttpResponse.json(dayPlanOf(jobId, resumeId, plan));
    }),
  ];
}
