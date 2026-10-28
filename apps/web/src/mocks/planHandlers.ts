/**
 * MSW handlers for the interview plan page (PP-1, PP-2), with the shapes in openapi.json. Like
 * the API, the view is put together from the other endpoints: the job, the CV, the gap
 * analysis, the reports and the progress, which are mocked in handlers.ts. The interview date
 * lives here, per mock database, so a store reset clears it.
 */
import { http, HttpResponse } from "msw/http";

import type {
  Competency,
  GapAnalysisOut,
  InterviewType,
  JobProgress,
  JobTargetOut,
  ReportItem,
  ResumeOut,
} from "../api/types";
import type { PlanView, TypeWeights } from "../pages/plan/api";
import type { MockDb, MockStore } from "./db";

const API = "*/api";

const STANDARD: [InterviewType, Competency[]][] = [
  ["behavioral", ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"]],
  ["hiring_manager", ["role_fit", "depth_of_experience", "judgment", "motivation", "team_fit", "scope_at_level"]],
  ["technical_qa", ["technical_depth", "accuracy", "reasoning", "trade_offs", "clarity_of_explanation"]],
  ["case", ["problem_framing", "structure", "user_and_business_sense", "estimation_logic", "prioritization", "recommendation"]],
];

/** Generic mode: equal weights (the mock has no curated profiles). */
function equalWeights(): TypeWeights[] {
  return STANDARD.map(([interview_type, comps]) => ({
    interview_type,
    in_loop: false,
    competencies: comps.map((competency) => ({ competency, weight: 1, share: Math.round(1000 / comps.length) / 1000 })),
  }));
}

function daysLeft(date: string | null): number | null {
  if (!date) return null;
  const today = new Date().toISOString().slice(0, 10);
  return Math.round((Date.parse(date) - Date.parse(today)) / 86_400_000);
}

export function planHandlers(store: MockStore) {
  const dates = new WeakMap<MockDb, Record<string, string | null>>();
  const datesOf = () => {
    let map = dates.get(store.db);
    if (!map) dates.set(store.db, (map = {}));
    return map;
  };

  return [
    http.get(`${API}/plan/:jobId/:resumeId`, async ({ params, request }) => {
      const base = new URL(request.url).origin + "/api";
      const jobId = String(params.jobId);
      const resumeId = String(params.resumeId);
      const get = (path: string) => fetch(`${base}${path}`, { headers: request.headers });
      const [jobRes, cvRes] = await Promise.all([get(`/job-targets/${jobId}`), get(`/resumes/${resumeId}`)]);
      if (!jobRes.ok) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      if (!cvRes.ok) return HttpResponse.json({ detail: "Resume not found" }, { status: 404 });
      const job = (await jobRes.json()) as JobTargetOut;
      const resume = (await cvRes.json()) as ResumeOut;
      const gapRes = await get(`/job-targets/${jobId}/gap-analysis`);
      const latest = gapRes.ok ? ((await gapRes.json()) as GapAnalysisOut) : null;
      const gap = latest && latest.resume_id === resumeId ? latest : null;
      const reports = (await (await get(`/reports?job_target_id=${jobId}&resume_id=${resumeId}`)).json()) as ReportItem[];
      const progressRes = await get(`/job-targets/${jobId}/progress`);
      const progress = progressRes.ok ? ((await progressRes.json()) as JobProgress) : null;

      const plan = gap?.analysis?.session_plan ?? [];
      const first = [...plan].sort((a, b) => a.priority - b.priority)[0] ?? null;
      const next = progress?.next_session ?? first;
      const date = datesOf()[jobId] ?? null;
      const view: PlanView = {
        job,
        resume,
        company_mode: "generic",
        company_name: job.posting?.company_name ?? null,
        values_framework: null,
        interview_date: date,
        days_left: daysLeft(date),
        tested: equalWeights(),
        gap,
        reports,
        next_session: progress?.next_session ?? null,
        next_custom_session: progress?.next_custom_session ?? null,
        setup: {
          interview_type: next?.interview_type ?? "behavioral",
          difficulty: next?.difficulty ?? "realistic",
          mode: "coach",
          duration_min: 30,
          level: job.level,
          tone: "neutral",
        },
      };
      return HttpResponse.json(view);
    }),
    http.put(`${API}/plan/:jobId/interview-date`, async ({ params, request }) => {
      const { interview_date } = (await request.json()) as { interview_date: string | null };
      const left = daysLeft(interview_date);
      if (left !== null && left < -1) {
        return HttpResponse.json({ detail: "Choose today or a later date." }, { status: 422 });
      }
      datesOf()[String(params.jobId)] = interview_date;
      return HttpResponse.json({ interview_date, days_left: left });
    }),
  ];
}
