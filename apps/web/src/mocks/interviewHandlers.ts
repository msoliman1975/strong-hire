/**
 * MSW handlers for U06, with the shapes in openapi.json: suggested interviews (TG-3), interviews
 * per role (RH-1) and readiness per interview (RH-2). Takes are the mock sessions with the same
 * job, resume and type. Readiness here is a stand-in that grows with completed Realistic takes,
 * shaped like the mockup's samples (58, then 66); the API computes it from scorecards.
 */
import { http, HttpResponse } from "msw/http";

import type {
  InterviewDetail,
  InterviewOut,
  InterviewTakeOut,
  InterviewWithReadiness,
  JobTargetOut,
  RehearsalItem,
  RoleSummary,
  SessionRecord,
  SuggestedInterviews,
} from "../api/types";
import type { MockStore } from "./db";
import { newId } from "./db";

const API = "*/api";
const GOAL = 75;

type Kind = InterviewOut["interview_type"];
type Competency = InterviewWithReadiness["readiness"]["competencies"][number]["competency"];

const COMPETENCIES: Record<Kind, Competency[]> = {
  behavioral: ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"],
  hiring_manager: ["role_fit", "depth_of_experience", "judgment", "motivation", "team_fit", "scope_at_level"],
  technical_qa: ["technical_depth", "accuracy", "reasoning", "trade_offs", "clarity_of_explanation"],
  case: ["problem_framing", "structure", "user_and_business_sense", "estimation_logic", "prioritization", "recommendation"],
  recruiter_screen: ["motivation", "communication", "role_fit", "logistics_and_expectations"],
  custom: [],
};

const TITLES: Record<Kind, string> = {
  behavioral: "Engineering Manager",
  hiring_manager: "Hiring Manager",
  technical_qa: "Senior Engineer",
  case: "Product Lead",
  recruiter_screen: "Recruiter",
  custom: "Interviewer",
};

const DESCRIPTIONS: Record<Kind, string> = {
  behavioral: "Past situations: ownership, conflict, impact and what you learned.",
  hiring_manager: "Your experience in depth: judgment, scope and fit for the team.",
  technical_qa: "Talk through technical topics: depth, accuracy and trade-offs.",
  case: "Work a business or product problem out loud, with a recommendation.",
  recruiter_screen: "Motivation, background and logistics, in a short first call.",
  custom: "Your own mix of question types and questions.",
};

const STANDARD: Kind[] = ["behavioral", "hiring_manager", "technical_qa"];
const ALL: Kind[] = ["behavioral", "hiring_manager", "technical_qa", "case", "recruiter_screen"];

function company(job: JobTargetOut): string | null {
  return job.generic_mode === false ? (job.posting?.company_name ?? null) : null;
}

function actingAs(job: JobTargetOut, kind: Kind): InterviewOut["acting_as"] {
  const title = TITLES[kind];
  const at = company(job);
  const article = /^[aeiou]/i.test(title) ? "an" : "a";
  return { title, company: at, text: at ? `Strova is acting as ${title} at ${at}` : `Strova is acting as ${article} ${title}` };
}

function daysLeft(when: string | null | undefined): number | null {
  if (!when) return null;
  const today = new Date(new Date().toISOString().slice(0, 10));
  return Math.round((new Date(when).getTime() - today.getTime()) / 86_400_000);
}

export function interviewHandlers(store: MockStore) {
  const db = () => store.db;
  const interviews = () => (db().interviews ??= []);
  const job = (id: unknown) => db().jobs.find((j) => j.id === id);

  const role = (j: JobTargetOut): RoleSummary => {
    const when = db().interviewDates?.[j.id] ?? null;
    return {
      id: j.id,
      name: j.name,
      title: j.posting?.title ?? null,
      company_name: j.posting?.company_name ?? null,
      company_mode: j.generic_mode === false ? "curated" : "generic",
      interview_date: when,
      days_left: daysLeft(when),
      archived: Boolean(j.archived_at),
    };
  };

  const sessionsOf = (i: InterviewOut): SessionRecord[] =>
    db()
      .sessions.filter(
        (s) => s.job_target_id === i.job_target_id && s.resume_id === i.resume_id && s.config.interview_type === i.interview_type,
      )
      .reverse();

  const withReadiness = (i: InterviewOut): InterviewWithReadiness => {
    const takes = sessionsOf(i);
    const counted = takes.filter((s) => s.config.mode === "realistic" && s.status === "completed");
    const score = counted.length === 0 ? null : Math.min(100, 50 + 8 * counted.length);
    const comps = COMPETENCIES[i.interview_type];
    return {
      interview: i,
      readiness: {
        interview_id: i.id,
        kind: "practice_estimate",
        score,
        goal: GOAL,
        competencies: comps.map((c, n) => ({ competency: c, score: score === null ? null : Math.max(1, Math.min(4, 2 + ((n + counted.length) % 3))) })),
        change: counted.length >= 2 ? 8 : null,
        takes_counted: Math.min(counted.length, 3),
      },
      takes_count: takes.length,
      last_signal: counted.length ? "Lean Hire" : null,
    };
  };

  const live = (jobId: string) => interviews().filter((i) => i.job_target_id === jobId && !i.archived_at);

  return [
    http.get(`${API}/roles/:jobId/suggested-interviews`, ({ params }) => {
      const j = job(params.jobId);
      if (!j || j.deleted) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      const body: SuggestedInterviews = {
        company_mode: j.generic_mode === false ? "curated" : "generic",
        items: ALL.map((k) => ({
          interview_type: k,
          description: DESCRIPTIONS[k],
          usual: STANDARD.includes(k),
          round_name: null,
          acting_as: actingAs(j, k),
        })),
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/roles/:jobId/interviews`, ({ params }) => {
      const j = job(params.jobId);
      if (!j) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      return HttpResponse.json(live(j.id).map(withReadiness));
    }),

    http.post(`${API}/roles/:jobId/interviews`, async ({ params, request }) => {
      const j = job(params.jobId);
      if (!j || j.deleted) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      const body = (await request.json()) as { resume_id?: string | null; interview_types: Kind[] };
      const out = addMockInterviews(store, j, body.interview_types, body.resume_id);
      if (!out) return HttpResponse.json({ detail: "Add a resume first." }, { status: 409 });
      store.save();
      return HttpResponse.json(out, { status: 201 });
    }),

    http.delete(`${API}/interviews/:interviewId`, ({ params }) => {
      const row = interviews().find((i) => i.id === params.interviewId);
      if (!row) return HttpResponse.json({ detail: "Interview not found" }, { status: 404 });
      row.archived_at ??= new Date().toISOString();
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),

    http.get(`${API}/interviews/:interviewId`, ({ params }) => {
      const row = interviews().find((i) => i.id === params.interviewId);
      const j = row ? job(row.job_target_id) : undefined;
      if (!row || !j) return HttpResponse.json({ detail: "Interview not found" }, { status: 404 });
      const takes = sessionsOf(row);
      const body: InterviewDetail = {
        ...withReadiness(row),
        role: role(j),
        resume_name: db().resumes.find((r) => r.id === row.resume_id)?.name ?? null,
        takes: takes.map(
          (s, n): InterviewTakeOut => ({
            number: takes.length - n,
            session_id: s.id,
            mode: s.config.mode,
            status: s.status,
            at: s.started_at ?? new Date().toISOString(),
            duration_min: s.config.duration_min,
            hire_signal: s.status === "completed" ? "Lean Hire" : null,
            met_bar: s.status === "completed" ? 3 : null,
            scored: s.status === "completed" ? 5 : null,
            counts: s.status === "completed" && s.config.mode === "realistic",
          }),
        ),
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/roles`, () => {
      const roles = [...db().jobs]
        .filter((j) => !j.deleted && !j.archived_at)
        .reverse()
        .map((j) => ({ role: role(j), interviews: live(j.id).map(withReadiness) }));
      return HttpResponse.json(roles);
    }),

    http.get(`${API}/rehearsals`, () => {
      const items: RehearsalItem[] = [...db().jobs]
        .filter((j) => !j.deleted && !j.archived_at)
        .reverse()
        .flatMap((j) => live(j.id).map((i) => ({ ...withReadiness(i), role: role(j) })));
      const below = items.filter((i) => i.readiness.score === null || i.readiness.score < GOAL);
      below.sort(
        (a, b) =>
          Number(a.role.interview_date === null) - Number(b.role.interview_date === null) ||
          (a.role.interview_date ?? "").localeCompare(b.role.interview_date ?? "") ||
          (a.readiness.score ?? -1) - (b.readiness.score ?? -1),
      );
      return HttpResponse.json({ items, next_interview_id: below[0]?.interview.id ?? null });
    }),
  ];
}

/** RH-1: a take of an interview gets its type and resume (used by the mock POST /sessions). */
export function interviewForTake(store: MockStore, id: string | null | undefined): InterviewOut | undefined {
  return id ? store.db.interviews?.find((i) => i.id === id && !i.archived_at) : undefined;
}

/** RH-1: keep the types as interviews of the role on the resume (default: the main one). Reuses
 * a live interview of the same type. Undefined when the user has no resume. The caller saves. */
export function addMockInterviews(
  store: MockStore,
  j: JobTargetOut,
  types: Kind[],
  resumeId?: string | null,
): InterviewOut[] | undefined {
  const all = (store.db.interviews ??= []);
  const resumes = store.db.resumes;
  const resume =
    resumes.find((r) => r.id === resumeId && !r.deleted) ??
    resumes.find((r) => r.is_main && !r.deleted) ??
    [...resumes].reverse().find((r) => !r.deleted);
  if (!resume) return undefined;
  return [...new Set(types)].map((kind) => {
    const found = all.find(
      (i) => i.job_target_id === j.id && !i.archived_at && i.interview_type === kind && i.resume_id === resume.id,
    );
    if (found) return found;
    const row: InterviewOut = {
      id: newId(),
      job_target_id: j.id,
      resume_id: resume.id,
      interview_type: kind,
      custom: null,
      created_at: new Date().toISOString(),
      archived_at: null,
      acting_as: actingAs(j, kind),
    };
    all.push(row);
    return row;
  });
}
