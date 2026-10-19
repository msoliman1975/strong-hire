/**
 * MSW handlers for Simulations (SM), with the same paths and shapes as openapi.json. Only
 * admin@example.com gets answers. The state lives per mock database: one finished admin run with a
 * replay, and one suite run. Pausing in the Controls mock closes the gate here too.
 */
import { http, HttpResponse } from "msw/http";

import type { SessionReplay, SimOptions, SimRun, SimRunIn, SimRunStatus } from "../api/sim";
import { opsState } from "./controlsHandlers";
import { newId, type MockDb, type MockStore } from "./db";
import { API, currentAdmin } from "./handlers";

export const MOCK_SIM_SESSION = "00000000-0000-4000-8000-0000000005e1";
const MAX_WAITING = 5;
const FINISHED: SimRunStatus[] = ["done", "failed", "cancelled"];
const PENDING: SimRunStatus[] = ["queued", "waiting"];
const VOICE_ONLY = ["interrupts", "drops_connection"];

const PERSONAS = [
  { id: "backend-senior", label: "Senior backend engineer", posting: "swe-stripe-backend", level: "senior" },
  { id: "ml-engineer-staff", label: "Staff ML engineer", posting: "data-databricks-ml-serving", level: "staff_principal" },
  { id: "new-grad-swe", label: "New grad software engineer", posting: "swe-northwind-newgrad", level: "new_grad" },
  { id: "product-manager-mid", label: "Product manager", posting: "pm-shopify-checkout", level: "mid" },
  { id: "product-designer-senior", label: "Senior product designer", posting: "design-airbnb-product-designer", level: "senior" },
  { id: "tpm-career-changer", label: "TPM, career changer", posting: "tpm-harbor-robotics", level: "mid" },
] as const;

const BEHAVIORS = [
  "normal",
  "long_answers",
  "one_line_answers",
  "off_topic",
  "asks_to_repeat",
  "silent",
  "interrupts",
  "argues",
  "many_questions_back",
  "prompt_injection",
  "drops_connection",
] as const;

export interface SimState {
  runs: SimRun[];
  replays: Record<string, SessionReplay>;
  /** Tests set these to close the gate the way the real API would. */
  liveLimitReason: string | null;
  budget: SimOptions["budget"];
}

function scenario(overrides: Partial<SimRun["scenario"]> = {}): SimRun["scenario"] {
  return {
    channel: "voice",
    interview_type: "behavioral",
    difficulty: "realistic",
    mode: "realistic",
    duration_min: 10,
    persona: "backend-senior",
    quality: "strong",
    behavior: "normal",
    candidate_name: "Ada Venn",
    custom_job: false,
    custom_cv: false,
    level: null,
    ...overrides,
  };
}

function run(overrides: Partial<SimRun> = {}): SimRun {
  return {
    id: newId(),
    source: "admin",
    suite: null,
    run_dir: null,
    created_by: "admin@example.com",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    status: "queued",
    status_reason: null,
    scenario: scenario(),
    session_id: null,
    progress_s: 0,
    planned_s: 600,
    hire_signal: null,
    failed_rules: [],
    problems: 0,
    latency_p50_ms: null,
    cost_sim_usd: 0,
    cost_app_usd: null,
    cost_total_usd: 0,
    keep: false,
    deleted_at: null,
    deleted_by: null,
    delete_reason: null,
    files: false,
    inputs: null,
    ...overrides,
  };
}

export const mockReplay: SessionReplay = {
  session_id: MOCK_SIM_SESSION,
  run_dir: "20261018-100000-admin-ab12",
  sim_run_id: "00000000-0000-4000-8000-0000000005a1",
  channel: "voice",
  timing: "audio",
  lines: [
    { speaker: "interviewer", text: "Hi, I am Alex. Thanks for joining.", start_ms: 1_000, end_ms: 3_500, phase: "intro", note: null, latency_ms: null },
    { speaker: "candidate", text: "Happy to be here.", start_ms: 4_000, end_ms: 5_500, phase: "intro", note: null, latency_ms: null },
    { speaker: "interviewer", text: "Tell me about a project you owned.", start_ms: 6_100, end_ms: 9_000, phase: "core", note: null, latency_ms: 600 },
    { speaker: "candidate", text: "I led the billing rebuild.", start_ms: 9_500, end_ms: 20_000, phase: "core", note: null, latency_ms: null },
    { speaker: "interviewer", text: "What went wrong?", start_ms: 21_200, end_ms: 22_500, phase: "core", note: null, latency_ms: 1_200 },
    { speaker: "candidate", text: "...", start_ms: 23_000, end_ms: 29_000, phase: "core", note: "silent for 6 s", latency_ms: null },
    { speaker: "interviewer", text: "Take your time.", start_ms: 31_000, end_ms: 32_000, phase: "core", note: null, latency_ms: 2_000 },
  ],
  latency: { n: 3, p50_ms: 1_200, p90_ms: 2_000, slow_turns: 1, ok_ms: 800, slow_ms: 1_500 },
  judge: {
    rubric: "judge/transcript.v1",
    model: "sim-judge",
    rules: [
      { rule: "tone", verdict: "pass", reason: "Warm throughout." },
      { rule: "no_repetition", verdict: "fail", reason: "Asked the same thing at 00:21 and 00:31." },
      { rule: "injection", verdict: "not_applicable", reason: "No injection attempt." },
    ],
    problems: [{ at: "00:31", at_ms: 31_000, problem: "Repeated the question" }],
  },
  scorecard: {
    hire_signal: "Lean Hire",
    rationale: "Clear ownership of the billing rebuild, thin on what went wrong.",
    competency_scores: [
      { competency: "ownership", score: 3, justification: "Led the rebuild end to end.", quotes: ["I led the billing rebuild."] },
    ],
    value_scores: [],
    per_question: [],
    scorer_model: "fake-scorer",
    rubric_version: "scorer/rubric.v1",
  },
  audio: { available: true, bytes: 48_000 },
  scenario: scenario(),
  inputs: null,
};

const states = new WeakMap<MockDb, SimState>();

export function simState(db: MockDb): SimState {
  let state = states.get(db);
  if (!state) {
    state = {
      runs: [
        run({
          id: "00000000-0000-4000-8000-0000000005a1",
          run_dir: "20261018-100000-admin-ab12",
          created_at: "2026-10-18T10:00:00Z",
          started_at: "2026-10-18T10:00:02Z",
          finished_at: "2026-10-18T10:11:40Z",
          status: "done",
          session_id: MOCK_SIM_SESSION,
          progress_s: 610,
          hire_signal: "Lean Hire",
          failed_rules: ["no_repetition"],
          problems: 1,
          latency_p50_ms: 1_200,
          cost_sim_usd: 0.05,
          cost_app_usd: 0.03,
          cost_total_usd: 0.08,
          files: true,
        }),
        run({
          id: "20261001-090000-text-smoke-cd34/beh-weak",
          source: "suite",
          suite: "text-smoke",
          run_dir: "20261001-090000-text-smoke-cd34",
          created_by: null,
          created_at: "2026-10-01T09:00:00Z",
          status: "failed",
          status_reason: "provider down",
          scenario: scenario({ channel: "text", persona: "new-grad-swe", quality: "weak", candidate_name: null }),
          session_id: "00000000-0000-4000-8000-0000000005e2",
          files: true,
          cost_sim_usd: 0.01,
          cost_total_usd: 0.01,
        }),
      ],
      replays: { [MOCK_SIM_SESSION]: structuredClone(mockReplay) },
      liveLimitReason: null,
      budget: { limit_usd: 5, spent_usd: 1.25, left_usd: 3.75, resets_at: null },
    };
    states.set(db, state);
  }
  return state;
}

function estimate(minutes: number) {
  const turns = { 10: 12, 30: 30, 45: 40 }[minutes] ?? 30;
  const candidate = (turns * (3000 * 1.5 + 120 * 9)) / 1e6;
  const judge = (12000 * 2 + 1200 * 10) / 1e6;
  const server = { 10: 0.03, 30: 0.08, 45: 0.11 }[minutes] ?? 0.08;
  const r = (x: number) => Number(x.toFixed(4));
  return {
    duration_min: minutes,
    candidate_usd: r(candidate),
    judge_usd: r(judge),
    main_server_usd: r(server),
    total_usd: r(candidate + judge + server),
  };
}

export function simHandlers(store: MockStore) {
  const admin = () => currentAdmin(store.db)?.email ?? null;
  const notFound = (detail = "Not Found") => HttpResponse.json({ detail }, { status: 404 });
  const forbidden = () => HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
  const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 });
  const state = () => simState(store.db);

  const gate = (): SimOptions["gate"] => {
    if (opsState(store.db).values.sim_paused) {
      return { ok: false, retry: false, reason: "AI candidate runs are paused (Controls)" };
    }
    const reason = state().liveLimitReason;
    return reason ? { ok: false, retry: true, reason } : { ok: true, retry: false, reason: null };
  };
  const queue = () => {
    const live = state().runs.filter((r) => r.source === "admin" && !r.deleted_at);
    return {
      active: live.filter((r) => ["starting", "interviewing", "judging"].includes(r.status)).length,
      waiting: live.filter((r) => PENDING.includes(r.status)).length,
      max_waiting: MAX_WAITING,
    };
  };
  const find = (id: string) => state().runs.find((r) => r.id === id && r.source === "admin");
  const write = (request: Request) => request.headers.get("X-Admin-Request") === "1";

  return [
    http.get(`${API}/admin/sim/options`, () => {
      if (!admin()) return notFound();
      const body: SimOptions = {
        personas: PERSONAS.map((p) => ({ ...p })),
        interview_types: ["behavioral", "hiring_manager", "technical_qa", "case"],
        difficulties: ["friendly", "realistic", "tough"],
        modes: ["coach", "realistic"],
        durations: [10, 30, 45],
        qualities: ["strong", "average", "weak"],
        behaviors: BEHAVIORS.map((b) => ({ id: b, voice_only: VOICE_ONLY.includes(b) })),
        channels: ["voice", "text"],
        estimates: [10, 30, 45].map(estimate),
        budget: state().budget,
        gate: gate(),
        queue: queue(),
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/admin/sim/runs`, ({ request }) => {
      if (!admin()) return notFound();
      const q = new URL(request.url).searchParams;
      let runs = [...state().runs];
      if (q.get("status")) runs = runs.filter((r) => r.status === q.get("status"));
      if (q.get("channel")) runs = runs.filter((r) => r.scenario.channel === q.get("channel"));
      if (q.get("source")) runs = runs.filter((r) => r.source === q.get("source"));
      runs.sort((a, b) => b.created_at.localeCompare(a.created_at));
      runs = runs.map((r) => ({ ...r, inputs: null }));
      const anyUnfinished = state().runs.some((r) => r.source === "admin" && !FINISHED.includes(r.status));
      return HttpResponse.json({ runs, any_unfinished: anyUnfinished });
    }),

    http.post(`${API}/admin/sim/runs`, async ({ request }) => {
      const who = admin();
      if (!who) return notFound();
      if (!write(request)) return forbidden();
      const body = (await request.json()) as SimRunIn;
      const channel = body.channel ?? "voice";
      if (VOICE_ONLY.includes(body.behavior ?? "normal") && channel !== "voice") {
        return HttpResponse.json(
          { detail: [{ msg: `Value error, behavior ${body.behavior} needs the voice channel` }] },
          { status: 422 },
        );
      }
      if (queue().waiting >= MAX_WAITING) {
        return conflict(`${queue().waiting} runs are already waiting; try again when one has started`);
      }
      const g = gate();
      if (!g.ok) return conflict(g.reason ?? "AI candidate runs cannot start now");
      const minutes = body.duration_min ?? 30;
      const jobText = body.job_text?.trim() || null;
      const cvText = body.cv_text?.trim() || null;
      if (jobText && !body.level) {
        return HttpResponse.json(
          { detail: [{ msg: "Value error, level is required when a job posting is pasted" }] },
          { status: 422 },
        );
      }
      const level = jobText ? (body.level ?? null) : null;
      const created = run({
        inputs: jobText || cvText ? { job_text: jobText, cv_text: cvText, level } : null,
        created_by: who,
        planned_s: minutes * 60,
        scenario: scenario({
          channel,
          interview_type: body.interview_type ?? "behavioral",
          difficulty: body.difficulty ?? "realistic",
          mode: body.mode ?? "realistic",
          duration_min: minutes,
          persona: body.persona,
          quality: body.quality ?? "average",
          behavior: body.behavior ?? "normal",
          candidate_name: "Mira Ostrand",
          custom_job: jobText !== null,
          custom_cv: cvText !== null,
          level,
        }),
      });
      state().runs.unshift(created);
      return HttpResponse.json(created, { status: 201 });
    }),

    http.get(`${API}/admin/sim/runs/:runId`, ({ params }) => {
      if (!admin()) return notFound();
      const found = find(String(params.runId));
      return found ? HttpResponse.json(found) : notFound("Run not found");
    }),

    http.patch(`${API}/admin/sim/runs/:runId`, async ({ params, request }) => {
      if (!admin()) return notFound();
      if (!write(request)) return forbidden();
      const found = find(String(params.runId));
      if (!found) return notFound("Run not found");
      if (found.deleted_at) return conflict("The run's files are deleted");
      found.keep = ((await request.json()) as { keep: boolean }).keep;
      return HttpResponse.json(found);
    }),

    http.delete(`${API}/admin/sim/runs/:runId`, async ({ params, request }) => {
      const who = admin();
      if (!who) return notFound();
      if (!write(request)) return forbidden();
      const found = find(String(params.runId));
      if (!found) return notFound("Run not found");
      const body = (await request.json()) as { reason?: string };
      if (!body.reason || body.reason.trim().length < 3) {
        return HttpResponse.json({ detail: [{ msg: "reason: at least 3 characters" }] }, { status: 422 });
      }
      if (!FINISHED.includes(found.status)) return conflict("The run is not finished; cancel it first");
      if (found.deleted_at) return conflict("The run is already deleted");
      Object.assign(found, {
        deleted_at: new Date().toISOString(),
        deleted_by: who,
        delete_reason: body.reason,
        files: false,
        inputs: null,
      });
      return HttpResponse.json(found);
    }),

    http.post(`${API}/admin/sim/runs/:runId/cancel`, ({ params, request }) => {
      if (!admin()) return notFound();
      if (!write(request)) return forbidden();
      const found = find(String(params.runId));
      if (!found) return notFound("Run not found");
      if (FINISHED.includes(found.status)) return conflict(`The run is already ${found.status}`);
      if (PENDING.includes(found.status)) {
        Object.assign(found, {
          status: "cancelled",
          status_reason: "cancelled before it started",
          finished_at: new Date().toISOString(),
        });
      }
      return HttpResponse.json(found);
    }),

    http.get(`${API}/admin/sessions/:sessionId/replay`, ({ params }) => {
      if (!admin()) return notFound();
      const replay = state().replays[String(params.sessionId)];
      return replay ? HttpResponse.json(replay) : notFound("Replay is for AI candidate interviews");
    }),
  ];
}
