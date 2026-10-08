/**
 * MSW handlers for the admin area (R2), with the same paths and shapes as openapi.json.
 *
 * In the mock, admin@example.com is the admin (ADMIN_EMAILS in the real API). Everyone else gets
 * 404. Every session in the mock store belongs to the first user who is not an admin. The
 * transcript and the traces are fixtures, shown only while that user's consent is on, and each
 * view adds two audit entries, like the real API.
 */
import { http, HttpResponse } from "msw/http";

import type {
  AdminAuditEntry,
  AdminSession,
  AdminSessionDetail,
  AdminSessionList,
  AdminTrace,
  AdminUser,
  DailyCost,
} from "../api/admin";
import type { AuthUser, SessionRecord, Turn } from "../api/types";
import { newId, type MockDb, type MockStore } from "./db";

const API = "*/api";
const SESSION_LIMIT = 500;
const MOCK_COST_USD = 0.0123;

export const MOCK_ADMIN_EMAILS = ["admin@example.com"];

export function isMockAdmin(email: string): boolean {
  return MOCK_ADMIN_EMAILS.includes(email.trim().toLowerCase());
}

/** Audit entries per mock database, so a store reset starts a new log. */
const audits = new WeakMap<MockDb, AdminAuditEntry[]>();

function auditLog(db: MockDb): AdminAuditEntry[] {
  let log = audits.get(db);
  if (!log) {
    log = [];
    audits.set(db, log);
  }
  return log;
}

function notFound() {
  return HttpResponse.json({ detail: "Not Found" }, { status: 404 });
}

export const mockTranscript: Turn[] = [
  { speaker: "interviewer", phase: "intro", text: "Hi, I am Alex. Thanks for joining.", start_ms: 0, end_ms: 3_000, question_ref: null },
  { speaker: "candidate", phase: "intro", text: "Happy to be here.", start_ms: 4_000, end_ms: 5_500, question_ref: null },
  {
    speaker: "interviewer",
    phase: "core",
    text: "Tell me about a project you owned from start to finish.",
    start_ms: 62_000,
    end_ms: 66_000,
    question_ref: "q1",
  },
  {
    speaker: "candidate",
    phase: "core",
    text: "I led the move of our billing service to a new queue.",
    start_ms: 68_000,
    end_ms: 80_000,
    question_ref: "q1",
  },
  {
    speaker: "interviewer",
    phase: "core",
    text: "What changed for your users, in numbers?",
    start_ms: 82_000,
    end_ms: 84_000,
    question_ref: "q1",
  },
];

function trace(seq: number, at: string, changes: Partial<AdminTrace>): AdminTrace {
  return {
    seq,
    turn_index: 0,
    call: "say",
    move: "greet",
    reason: { why: ["start"], probes_used: 0, probe_limit: 2, time_left_in_phase_ms: 60_000 },
    phase: "intro",
    elapsed_ms: 0,
    phase_deadline_ms: 60_000,
    question_ref: null,
    messages: [
      { role: "system", content: "You are Alex, a job interviewer.", prompt_ref: "interviewer/turn.v2" },
      { role: "user", content: "Transcript so far: (nothing yet)\nMove: greet", prompt_ref: "interviewer/turn_input.v1" },
    ],
    raw_reply: "Hi, I am Alex. Thanks for joining.",
    spoken_text: "Hi, I am Alex. Thanks for joining.",
    model: "fake-interviewer",
    prompt_refs: "interviewer/turn.v2,interviewer/turn_input.v1",
    input_tokens: 650,
    output_tokens: 30,
    cost_usd: 0.0001,
    latency_ms: 420,
    error: null,
    created_at: at,
    ...changes,
  };
}

export function mockTraces(at: string): AdminTrace[] {
  return [
    trace(1, at, {}),
    trace(2, at, {
      move: "ask",
      phase: "core",
      turn_index: 2,
      elapsed_ms: 61_000,
      phase_deadline_ms: 540_000,
      question_ref: "q1",
      reason: { why: ["next_phase", "next_question"], probes_used: 0, probe_limit: 1, time_left_in_phase_ms: 479_000 },
      raw_reply: "Tell me about a project you owned from start to finish.",
      spoken_text: "Tell me about a project you owned from start to finish.",
    }),
    trace(3, at, {
      call: "decide",
      move: "decide",
      phase: "core",
      turn_index: 4,
      elapsed_ms: 80_000,
      phase_deadline_ms: 540_000,
      question_ref: "q1",
      reason: {
        decision: { action: "probe", missing: ["measurable_result"] },
        probes_used: 0,
        probe_limit: 1,
        time_left_in_phase_ms: 460_000,
      },
      raw_reply: '{"action":"probe","missing":["measurable_result"]}',
      spoken_text: null,
      prompt_refs: "interviewer/decide.v1,interviewer/decide_input.v1",
    }),
    trace(4, at, {
      move: "probe",
      phase: "core",
      turn_index: 4,
      elapsed_ms: 80_000,
      phase_deadline_ms: 540_000,
      question_ref: "q1",
      reason: {
        why: ["model_chose_probe"],
        missing: ["measurable_result"],
        decision: { action: "probe", missing: ["measurable_result"] },
        probes_used: 1,
        probe_limit: 1,
        time_left_in_phase_ms: 460_000,
      },
      raw_reply: "Interviewer: What changed for your users, in numbers?",
      spoken_text: "What changed for your users, in numbers?",
    }),
    trace(5, at, {
      call: "line",
      move: "take_your_time",
      phase: "core",
      turn_index: 5,
      elapsed_ms: 85_000,
      phase_deadline_ms: 540_000,
      question_ref: "q1",
      reason: { why: ["take_your_time"] },
      messages: null,
      raw_reply: null,
      spoken_text: "Sure, take your time. Go ahead whenever you are ready.",
      model: null,
      prompt_refs: null,
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: null,
      latency_ms: null,
    }),
  ];
}

export function adminHandlers(store: MockStore) {
  const db = () => store.db;
  const admin = (): AuthUser | null => {
    const { auth, users } = db();
    const user = auth.status === "signed_in" && auth.userEmail ? users[auth.userEmail] : undefined;
    return user && isMockAdmin(user.email) ? user : null;
  };
  const owner = (): AuthUser | undefined => {
    const users = Object.values(db().users);
    return users.find((u) => !isMockAdmin(u.email)) ?? users[0];
  };
  const createdAt = (s: SessionRecord) => s.started_at ?? "2026-10-07T09:00:00Z";

  const toAdmin = (s: SessionRecord): AdminSession => {
    const user = owner();
    const started = s.started_at ? Date.parse(s.started_at) : null;
    const ended = s.ended_at ? Date.parse(s.ended_at) : null;
    return {
      id: s.id,
      user_id: user?.id ?? null,
      user_email: user?.email ?? null,
      training_consent: Boolean(user?.training_consent),
      created_at: createdAt(s),
      started_at: s.started_at,
      ended_at: s.ended_at,
      interview_type: s.config.interview_type,
      difficulty: s.config.difficulty,
      mode: s.config.mode,
      duration_min: s.config.duration_min,
      duration_s: started !== null && ended !== null ? Math.round((ended - started) / 1000) : null,
      channel: s.channel,
      status: s.status,
      minutes_billed: s.minutes_billed,
      hire_signal: s.status === "completed" ? "Lean Hire" : null,
      scores: s.status === "completed" ? [{ competency: "ownership", score: 3 }] : [],
      model_profile: "fake",
      interviewer_model_id: "fake-interviewer",
      prompt_version: "interviewer/turn.v2,interviewer/turn_input.v1",
      cost_usd: s.started_at ? MOCK_COST_USD : null,
      cost_source: s.started_at ? "usage_events" : "none",
    };
  };

  return [
    http.get(`${API}/admin/users`, () => {
      if (!admin()) return notFound();
      const sessions = db().sessions.length;
      const ownerId = owner()?.id;
      const users: AdminUser[] = Object.values(db().users).map((u) => ({
        id: u.id,
        email: u.email,
        created_at: u.created_at,
        last_sign_in_at: u.created_at,
        plan: db().usage.plan,
        subscription_status: db().usage.status,
        minutes_used: db().usage.minutes_used,
        minutes_cap: db().usage.minutes_cap,
        training_consent: u.training_consent,
        interviews: u.id === ownerId ? sessions : 0,
        is_admin: isMockAdmin(u.email),
      }));
      return HttpResponse.json(users);
    }),

    http.get(`${API}/admin/sessions`, ({ request }) => {
      if (!admin()) return notFound();
      const query = new URL(request.url).searchParams;
      const userId = query.get("user_id");
      const type = query.get("interview_type");
      const from = query.get("day_from");
      const to = query.get("day_to");
      const sessions = db()
        .sessions.map(toAdmin)
        .filter((s) => !userId || s.user_id === userId)
        .filter((s) => !type || s.interview_type === type)
        .filter((s) => !from || s.created_at.slice(0, 10) >= from)
        .filter((s) => !to || s.created_at.slice(0, 10) <= to)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, SESSION_LIMIT);
      const byDay = new Map<string, AdminSession[]>();
      for (const s of sessions) byDay.set(s.created_at.slice(0, 10), [...(byDay.get(s.created_at.slice(0, 10)) ?? []), s]);
      const daily: DailyCost[] = [...byDay.entries()]
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([day, items]) => ({
          day,
          sessions: items.length,
          cost_usd: Number(items.reduce((sum, s) => sum + (s.cost_usd ?? 0), 0).toFixed(6)),
        }));
      const body: AdminSessionList = {
        sessions,
        daily,
        total_cost_usd: Number(daily.reduce((sum, d) => sum + d.cost_usd, 0).toFixed(6)),
        limit: SESSION_LIMIT,
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/admin/sessions/:sessionId`, ({ params }) => {
      const me = admin();
      if (!me) return notFound();
      const record = db().sessions.find((s) => s.id === params.sessionId);
      if (!record) return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
      const session = toAdmin(record);
      const visible = session.training_consent;
      const traces = visible ? mockTraces(session.created_at) : null;
      if (visible) {
        const at = new Date().toISOString();
        const details = { user_id: session.user_id };
        auditLog(db()).unshift(
          {
            id: newId(),
            at,
            actor: me.email,
            action: "admin.transcript_viewed",
            entity: `session:${session.id}`,
            org_id: null,
            details: { ...details, turns: mockTranscript.length },
          },
          {
            id: newId(),
            at,
            actor: me.email,
            action: "admin.traces_viewed",
            entity: `session:${session.id}`,
            org_id: null,
            details: { ...details, traces: traces?.length ?? 0 },
          },
        );
      }
      const body: AdminSessionDetail = {
        session,
        content_visible: visible,
        transcript: visible ? mockTranscript : null,
        traces,
        trace_retention_days: 90,
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/admin/audit`, ({ request }) => {
      if (!admin()) return notFound();
      const scope = new URL(request.url).searchParams.get("scope") ?? "admin";
      const entries = auditLog(db());
      return HttpResponse.json(scope === "all" ? entries : entries.filter((e) => e.action.startsWith("admin.")));
    }),
  ];
}
