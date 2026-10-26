/**
 * MSW handlers for the overview (AO) and operations routes (OB-10..OB-14), with the same paths
 * and shapes as openapi.json (src/mocks/fixtures.test.ts checks them). The numbers are fixed
 * fixtures; resolving an error group and retrying a job change the mock state, like the real API.
 */
import { http, HttpResponse } from "msw/http";

import type {
  AdminMetric,
  AdminOverview,
  OpsErrorDetail,
  OpsErrorGroup,
  OpsHealth,
  OpsJob,
  OpsJobs,
  OpsPerformance,
  OpsSpend,
} from "../api/ops";
import type { MockDb, MockStore } from "./db";
import { API, currentAdmin } from "./handlers";

export const MOCK_NOW = "2026-10-15T12:00:00Z";
const HOUR = 3_600_000;

function at(msBefore: number): string {
  return new Date(Date.parse(MOCK_NOW) - msBefore).toISOString();
}

function metric(value: number | null, previous: number | null, unit: AdminMetric["unit"] = "count", extra: Partial<AdminMetric> = {}): AdminMetric {
  return { measured: true, value, previous, unit, target: null, reason: null, note: null, link: null, ...extra };
}

function notMeasured(reason: string, unit: AdminMetric["unit"] = "count", extra: Partial<AdminMetric> = {}): AdminMetric {
  return { measured: false, value: null, previous: null, unit, target: null, reason, note: null, link: null, ...extra };
}

export function mockOverview(range: string): AdminOverview {
  const days = range === "24h" ? 1 : Number.parseInt(range, 10) || 7;
  const start = at(days * 24 * HOUR);
  const from = start.slice(0, 10);
  return {
    range: range as AdminOverview["range"],
    start,
    end: MOCK_NOW,
    previous_start: at(2 * days * 24 * HOUR),
    funnel: [
      { key: "signups", label: "Sign-ups", metric: metric(40, 32, "count", { link: "/users" }), conversion: null },
      { key: "activated", label: "Activated", metric: metric(26, 18), conversion: metric(0.65, 0.5625, "pct", { target: 0.6 }) },
      { key: "free_interview_done", label: "Free interview done", metric: metric(14, 10), conversion: metric(0.538462, 0.555556, "pct", { target: 0.5 }) },
      { key: "paid_14d", label: "Paid within 14 days", metric: metric(2, 1), conversion: metric(0.142857, 0.1, "pct", { target: 0.1 }) },
    ],
    revenue: {
      active_subscribers: metric(12, null, "count", { link: "/users?plan=paid" }),
      mrr_usd: metric(348, null, "usd"),
      new_subscriptions: metric(3, 2),
      cancellations: metric(1, 1),
      monthly_churn: metric(0.083333, 0.1, "pct", { target: 0.15 }),
      refunds: metric(0, 1),
    },
    usage: {
      sessions_started: metric(58, 44, "count", { link: `/interviews?from=${from}` }),
      sessions_completed: metric(51, 40, "count", { link: `/interviews?status=completed&from=${from}` }),
      sessions_failed: metric(1, 2, "count", { link: `/interviews?status=failed&from=${from}` }),
      minutes: metric(1220, 950, "minutes"),
      sessions_per_paid_user: metric(2.75, 2.4, "ratio", { target: 4 }),
      voice_sessions: metric(55, 42),
      text_sessions: metric(3, 2),
    },
    cost: {
      total_usd: metric(21.4, 17.9, "usd", { link: "/ops/spend" }),
      per_completed_session_usd: metric(0.38, 0.41, "usd", { target: 0.8 }),
      server_share_per_session_usd: metric(0.52, 0.61, "usd", { note: "$60 a month / sessions completed this calendar month" }),
      unmetered_rows: metric(102, 80),
      by_day: Array.from({ length: Math.min(days, 14) }, (_, i) => ({
        day: `${at((Math.min(days, 14) - 1 - i) * 24 * HOUR).slice(0, 10)}T00:00:00Z`,
        llm_usd: 1.2 + (i % 3) * 0.3,
        stt_usd: 0,
        tts_usd: 0.4 + (i % 2) * 0.1,
        total_usd: 1.6 + (i % 3) * 0.3 + (i % 2) * 0.1,
      })),
      by_component: [
        { key: "llm", cost_usd: 15.1, rows: 640 },
        { key: "tts", cost_usd: 6.3, rows: 410 },
        { key: "stt", cost_usd: 0, rows: 102 },
      ],
      by_role: [
        { key: "interviewer", cost_usd: 11.2, rows: 400 },
        { key: "tts", cost_usd: 6.3, rows: 410 },
        { key: "scorer", cost_usd: 2.9, rows: 51 },
        { key: "planner", cost_usd: 1.0, rows: 30 },
      ],
    },
    quality: {
      failure_rate: metric(0.017241, 0.045455, "pct", { target: 0.02, link: `/interviews?status=failed&from=${from}` }),
      voice_p50_ms: metric(760, 820, "ms", { target: 800, link: "/ops/performance" }),
      voice_p95_ms: metric(1410, 1620, "ms", { target: 1500, link: "/ops/performance" }),
      realism_rating: metric(4.3, 4.1, "rating", { target: 4.2, note: 'Average of 12 ratings, "felt like a real interview", 1 to 5' }),
      scorer_agreement: notMeasured("Measured by the eval harness against the human gold set (evals/), not in the app.", "pct"),
      offer_reported: notMeasured("The offer survey is not built yet."),
    },
  };
}

function points(n: number, step: number, f: (i: number) => number) {
  return Array.from({ length: n }, (_, i) => {
    const v = f(i);
    return { t: at((n - 1 - i) * step), value: v, min: v, max: v, n: 1 };
  });
}

export function mockHealth(): OpsHealth {
  const tile = (key: string, label: string, kind: "service" | "dependency", status: "up" | "degraded" | "down" | "unknown", extra: Partial<OpsHealth["tiles"][number]> = {}) => ({
    key,
    label,
    kind,
    status,
    detail: null,
    checked_at: at(60_000),
    latency_ms: null,
    version: null,
    instances: [],
    ...extra,
  });
  return {
    generated_at: MOCK_NOW,
    redis_error: null,
    tiles: [
      tile("api", "API", "service", "up", { version: "0.4.0", detail: "1 instance(s), profile fake" }),
      tile("worker", "Worker", "service", "up", {
        version: "0.4.0",
        instances: [{ service: "worker", instance: "w1", version: "0.4.0", model_profile: "fake", started_at: at(5 * HOUR), at: at(10_000) }],
      }),
      tile("voice", "Voice", "service", "down", { detail: "No heartbeat (OB-1)", checked_at: null }),
      tile("postgres", "Postgres", "dependency", "up", { latency_ms: 2.1 }),
      tile("redis", "Redis", "dependency", "up", { latency_ms: 0.8 }),
      tile("litellm", "LiteLLM", "dependency", "degraded", { detail: "The last probe is old; is the sampler running?" }),
      tile("livekit", "LiveKit", "dependency", "up", { latency_ms: 35 }),
      tile("stt", "Speech to text", "dependency", "up", { latency_ms: 40 }),
      tile("tts", "Text to speech", "dependency", "up", { latency_ms: 55 }),
      tile("smtp", "SMTP", "dependency", "unknown", { detail: "No probe samples yet (OB-6)", checked_at: null }),
      tile("stripe", "Stripe webhooks", "dependency", "up", { detail: "Last webhook 3.2 h ago" }),
    ],
    host: [
      { metric: "host.disk_pct", label: "Disk (root)", unit: "pct", labels: { mount: "root" }, latest: 61, latest_at: at(60_000), points: points(48, HOUR / 2, (i) => 55 + i / 8) },
      { metric: "host.mem_pct", label: "Memory", unit: "pct", labels: {}, latest: 72, latest_at: at(60_000), points: points(48, HOUR / 2, (i) => 60 + (i % 12)) },
      { metric: "host.load1", label: "Load (1 min)", unit: "ratio", labels: {}, latest: 0.8, latest_at: at(60_000), points: points(48, HOUR / 2, (i) => 0.5 + (i % 5) / 10) },
    ],
  };
}

export function mockPerformance(range: string): OpsPerformance {
  const keys = ["e2e", "turn_detection", "stt", "llm_ttft", "tts_ttfb", "other"];
  const base: Record<string, number> = { e2e: 760, turn_detection: 210, stt: 120, llm_ttft: 290, tts_ttfb: 95, other: 45 };
  return {
    range: range as OpsPerformance["range"],
    step_s: 3600,
    voice: keys.map((k) => ({ key: k, n: 320, p50_ms: base[k], p95_ms: Math.round(base[k] * 1.9) })),
    voice_series: keys.map((k) => ({
      key: k,
      points: Array.from({ length: 24 }, (_, i) => ({ t: at((23 - i) * HOUR), n: 12, p50_ms: base[k] + (i % 4) * 10, p95_ms: base[k] * 1.9 + (i % 5) * 20 })),
    })),
    llm_role: "interviewer",
    llm: [
      { key: "all", n: 410, p50_ms: 380, p95_ms: 910 },
      { key: "decide", n: 120, p50_ms: 520, p95_ms: 1100 },
      { key: "say", n: 290, p50_ms: 330, p95_ms: 780 },
    ],
    llm_series: [{ key: "all", points: Array.from({ length: 24 }, (_, i) => ({ t: at((23 - i) * HOUR), n: 17, p50_ms: 380, p95_ms: 900 })) }],
    llm_other_roles: notMeasured("Only interviewer calls are traced with their latency; extractor, planner and scorer calls are not timed yet.", "ms"),
    queue_wait: notMeasured("Arq does not keep enqueue and start times, so queue wait is not recorded yet.", "ms"),
  };
}

function seedErrors(): OpsErrorGroup[] {
  const spark = (peak: number) => Array.from({ length: 24 }, (_, i) => (i === 22 ? peak : i % 7 === 0 ? 1 : 0));
  return [
    {
      id: "00000000-0000-4000-8000-0000000000e1",
      fingerprint: "a1b2c3",
      service: "api",
      exception_type: "TimeoutError",
      message: "LiteLLM request timed out after 30 s",
      first_seen: at(3 * 24 * HOUR),
      last_seen: at(HOUR),
      count: 14,
      status: "open",
      resolved_at: null,
      resolved_by: null,
      release: "0.4.0",
      events_24h: spark(4).reduce((a, b) => a + b, 0),
      sparkline: spark(4),
    },
    {
      id: "00000000-0000-4000-8000-0000000000e2",
      fingerprint: "d4e5f6",
      service: "worker",
      exception_type: "KeyError",
      message: "'competency'",
      first_seen: at(9 * 24 * HOUR),
      last_seen: at(6 * 24 * HOUR),
      count: 2,
      status: "resolved",
      resolved_at: at(5 * 24 * HOUR),
      resolved_by: "admin@example.com",
      release: "0.3.9",
      events_24h: 0,
      sparkline: Array.from({ length: 24 }, () => 0),
    },
  ];
}

function seedJobs(): OpsJob[] {
  return [
    {
      kind: "gap_analysis",
      id: "00000000-0000-4000-8000-0000000000f1",
      state: "failed",
      status: "failed",
      reason: "We could not finish the analysis. Try again.",
      user_email: "ana@example.com",
      created_at: at(5 * HOUR),
      updated_at: at(5 * HOUR),
      retryable: true,
    },
    {
      kind: "scoring",
      id: "00000000-0000-4000-8000-0000000000f2",
      state: "stuck",
      status: "scoring",
      reason: "In scoring for 42 minutes.",
      user_email: "ana@example.com",
      created_at: at(HOUR),
      updated_at: at(42 * 60_000),
      retryable: true,
    },
  ];
}

interface OpsState {
  errors: OpsErrorGroup[];
  jobs: OpsJob[];
}

/** State per mock database, so a store reset starts over. */
const states = new WeakMap<MockDb, OpsState>();

function state(db: MockDb): OpsState {
  let s = states.get(db);
  if (!s) {
    s = { errors: seedErrors(), jobs: seedJobs() };
    states.set(db, s);
  }
  return s;
}

function detailOf(group: OpsErrorGroup): OpsErrorDetail {
  return {
    group,
    sample_stack: `Traceback (most recent call last):\n  File "strong_api/app.py", line 10, in handler\n${group.exception_type}: ${group.message}`,
    daily: Array.from({ length: 14 }, (_, i) => (i > 10 ? 3 : 0)),
    events: [{ at: group.last_seen, service: group.service, release: group.release, request_id: "req-1", session_id: null }],
  };
}

export function mockSpend(): OpsSpend {
  return {
    generated_at: MOCK_NOW,
    today_usd: 4.12,
    month_usd: 61.3,
    daily_cap_usd: 25,
    cap_pct: 0.1648,
    by_component: [
      { key: "llm", today_usd: 3.1, month_usd: 44.2 },
      { key: "tts", today_usd: 1.02, month_usd: 17.1 },
      { key: "stt", today_usd: 0, month_usd: 0 },
    ],
    by_role: [
      { key: "interviewer", today_usd: 2.4, month_usd: 33.9 },
      { key: "tts", today_usd: 1.02, month_usd: 17.1 },
      { key: "scorer", today_usd: 0.5, month_usd: 7.6 },
      { key: "planner", today_usd: 0.2, month_usd: 2.7 },
    ],
    daily: points(15, 24 * HOUR, (i) => 3 + (i % 4) * 0.8),
    litellm: { profile: "fake", tracked: false, today: null, month: null, rpm_limit: null },
    hosted_equivalent: {
      configured: false,
      reason: "Not configured: set SHADOW_STT_USD_PER_SECOND and SHADOW_TTS_USD_PER_CHARACTER.",
      stt_seconds: 42_000,
      tts_characters: 910_000,
      stt_usd_per_second: null,
      tts_usd_per_character: null,
      stt_usd: null,
      tts_usd: null,
      total_usd: null,
    },
  };
}

export function opsHandlers(store: MockStore) {
  const admin = () => currentAdmin(store.db);
  const notFound = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 });
  const needsWrite = (request: Request) =>
    request.headers.get("X-Admin-Request") === "1"
      ? null
      : HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });

  return [
    http.get(`${API}/admin/overview`, ({ request }) => {
      if (!admin()) return notFound();
      return HttpResponse.json(mockOverview(new URL(request.url).searchParams.get("range") ?? "7d"));
    }),
    http.get(`${API}/admin/ops/health`, () => (admin() ? HttpResponse.json(mockHealth()) : notFound())),
    http.get(`${API}/admin/ops/performance`, ({ request }) =>
      admin() ? HttpResponse.json(mockPerformance(new URL(request.url).searchParams.get("range") ?? "24h")) : notFound(),
    ),
    http.get(`${API}/admin/ops/errors`, ({ request }) => {
      if (!admin()) return notFound();
      const status = new URL(request.url).searchParams.get("status") ?? "open";
      const groups = state(store.db).errors.filter((g) => status === "all" || g.status === status);
      return HttpResponse.json(groups);
    }),
    http.get(`${API}/admin/ops/errors/:id`, ({ params }) => {
      if (!admin()) return notFound();
      const group = state(store.db).errors.find((g) => g.id === params.id);
      return group ? HttpResponse.json(detailOf(group)) : HttpResponse.json({ detail: "Error group not found" }, { status: 404 });
    }),
    http.patch(`${API}/admin/ops/errors/:id`, async ({ params, request }) => {
      const me = admin();
      if (!me) return notFound();
      const denied = needsWrite(request);
      if (denied) return denied;
      const body = (await request.json()) as { status: "open" | "resolved"; reason?: string };
      if (!body.reason || body.reason.trim().length < 3) {
        return HttpResponse.json({ detail: [{ msg: "reason is too short" }] }, { status: 422 });
      }
      const group = state(store.db).errors.find((g) => g.id === params.id);
      if (!group) return HttpResponse.json({ detail: "Error group not found" }, { status: 404 });
      group.status = body.status;
      group.resolved_by = body.status === "resolved" ? me.email : null;
      group.resolved_at = body.status === "resolved" ? new Date().toISOString() : null;
      return HttpResponse.json(detailOf(group));
    }),
    http.get(`${API}/admin/ops/jobs`, () => {
      if (!admin()) return notFound();
      const jobs = state(store.db).jobs;
      const body: OpsJobs = {
        queue_depth: metric(2, null, "count", { note: "Live, from Redis" }),
        queue_series: [{ metric: "queue.depth", labels: { queue: "arq:queue" }, points: points(24, HOUR, (i) => i % 3) }],
        jobs_paused: [],
        gap_analyses: jobs.filter((j) => j.kind === "gap_analysis"),
        scorings: jobs.filter((j) => j.kind === "scoring"),
      };
      return HttpResponse.json(body);
    }),
    http.post(`${API}/admin/ops/jobs/:kind/:id/retry`, async ({ params, request }) => {
      if (!admin()) return notFound();
      const denied = needsWrite(request);
      if (denied) return denied;
      const s = state(store.db);
      const job = s.jobs.find((j) => j.id === params.id && j.kind === params.kind);
      if (!job) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      s.jobs = s.jobs.filter((j) => j !== job);
      return HttpResponse.json(
        { kind: job.kind, id: job.id, job_id: `${job.kind}:${job.id}:retry`, status: job.kind === "scoring" ? "scoring" : "running" },
        { status: 202 },
      );
    }),
    http.get(`${API}/admin/ops/spend`, () => (admin() ? HttpResponse.json(mockSpend()) : notFound())),
  ];
}
