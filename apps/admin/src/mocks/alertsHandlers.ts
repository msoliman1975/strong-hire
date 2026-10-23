/**
 * MSW handlers for the alerts routes (AL-1, AL-4, AL-6), with the same paths and shapes as
 * openapi.json. Each mock database starts with three rules (one firing) and a short history.
 * Writes need `X-Admin-Request: 1` and a reason, like the real API.
 */
import { http, HttpResponse } from "msw/http";

import type { AlertEvent, AlertMetric, AlertRule, AlertRuleCreate, AlertRulePatch } from "../api/alerts";
import { newId, type MockDb, type MockStore } from "./db";
import { API, currentAdmin } from "./handlers";

export const mockAlertMetrics: AlertMetric[] = [
  { name: "heartbeat.up", description: "Service heartbeat present (1) or missing (0)", unit: "", labels: ["service"], derived: false, up: true, aggregation: null },
  { name: "probe.up", description: "Dependency probe passed (1) or failed (0)", unit: "", labels: ["dep"], derived: false, up: true, aggregation: null },
  { name: "host.disk_pct", description: "Disk used", unit: "%", labels: ["mount"], derived: false, up: false, aggregation: null },
  { name: "host.mem_pct", description: "Memory used", unit: "%", labels: [], derived: false, up: false, aggregation: null },
  { name: "queue.depth", description: "Jobs waiting in a queue", unit: "jobs", labels: ["queue"], derived: false, up: false, aggregation: null },
  { name: "spend.cap_pct", description: "Model cost since UTC midnight as a % of the daily spend cap", unit: "%", labels: [], derived: true, up: false, aggregation: "last" },
  { name: "errors.new_groups", description: "Error groups first seen in the window", unit: "groups", labels: [], derived: true, up: false, aggregation: "count" },
];

const DEFAULT_NAMES = new Set(["API down", "Disk filling", "Spend high"]);

function rule(id: string, changes: Partial<AlertRule>): AlertRule {
  return {
    id,
    name: "Rule",
    metric: "host.disk_pct",
    labels: null,
    aggregation: "last",
    window_s: 300,
    comparator: "gt",
    threshold: 85,
    min_samples: 1,
    for_s: 0,
    severity: "warning",
    renotify_s: 86_400,
    enabled: true,
    muted_until: null,
    state: "ok",
    state_since: null,
    last_notified_at: null,
    last_value: null,
    is_default: false,
    created_at: "2026-10-17T08:00:00Z",
    updated_at: null,
    ...changes,
  };
}

interface AlertsState {
  rules: AlertRule[];
  events: AlertEvent[];
}

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function seed(): AlertsState {
  const disk = rule("00000000-0000-4000-8000-0000000000e1", {
    name: "Disk filling",
    labels: { mount: "pgdata" },
    state: "firing",
    state_since: ago(95),
    last_notified_at: ago(95),
    last_value: 88.4,
    is_default: true,
  });
  const api = rule("00000000-0000-4000-8000-0000000000e2", {
    name: "API down",
    metric: "heartbeat.up",
    labels: { service: "api" },
    window_s: 120,
    comparator: "lt",
    threshold: 1,
    for_s: 120,
    severity: "critical",
    renotify_s: 14_400,
    last_value: 1,
    is_default: true,
  });
  const spend = rule("00000000-0000-4000-8000-0000000000e3", {
    name: "Spend high",
    metric: "spend.cap_pct",
    comparator: "gte",
    threshold: 80,
    last_value: 41.2,
    is_default: true,
  });
  const event = (id: string, r: AlertRule, kind: AlertEvent["kind"], at: string, value: number): AlertEvent => ({
    id,
    rule_id: r.id,
    rule_name: r.name,
    severity: r.severity,
    kind,
    value,
    at,
    notified: true,
    notify_error: null,
  });
  return {
    rules: [disk, api, spend],
    events: [
      event("00000000-0000-4000-8000-0000000000f2", disk, "fired", ago(95), 86.1),
      event("00000000-0000-4000-8000-0000000000f1", api, "resolved", ago(14 * 60), 1),
    ],
  };
}

const states = new WeakMap<MockDb, AlertsState>();

function stateOf(db: MockDb): AlertsState {
  let s = states.get(db);
  if (!s) {
    s = seed();
    states.set(db, s);
  }
  return s;
}

function withoutReason<T extends { reason: string }>(body: T): Omit<T, "reason"> {
  const copy: Partial<T> = { ...body };
  delete copy.reason;
  return copy as Omit<T, "reason">;
}

const notFound = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 });
const order = { firing: 0, pending: 1, ok: 2 } as const;

export function alertsHandlers(store: MockStore) {
  const admin = () => currentAdmin(store.db);
  const state = () => stateOf(store.db);

  /** null when the write is allowed, else the error response (AA-4, AA-5, AA-6). */
  const guard = (request: Request, body: { reason?: string } | null) => {
    if (!admin()) return notFound();
    if (request.headers.get("X-Admin-Request") !== "1") {
      return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
    }
    if (!body?.reason || body.reason.trim().length < 3) {
      return HttpResponse.json({ detail: [{ msg: "reason is required" }] }, { status: 422 });
    }
    return null;
  };
  const find = (id: unknown) => state().rules.find((r) => r.id === id);

  return [
    http.get(`${API}/admin/alerts/metrics`, () => (admin() ? HttpResponse.json(mockAlertMetrics) : notFound())),
    http.get(`${API}/admin/alerts/rules`, () => {
      if (!admin()) return notFound();
      const rules = [...state().rules].sort(
        (a, b) => order[a.state] - order[b.state] || a.name.localeCompare(b.name),
      );
      return HttpResponse.json(rules);
    }),
    http.post(`${API}/admin/alerts/rules`, async ({ request }) => {
      const body = (await request.json()) as AlertRuleCreate;
      const denied = guard(request, body);
      if (denied) return denied;
      if (!mockAlertMetrics.some((m) => m.name === body.metric)) {
        return HttpResponse.json({ detail: `Unknown metric '${body.metric}'` }, { status: 422 });
      }
      if (state().rules.some((r) => r.name === body.name)) {
        return HttpResponse.json({ detail: "A rule with this name exists" }, { status: 409 });
      }
      const fields = withoutReason(body);
      const created = rule(newId(), { ...fields, labels: fields.labels ?? null, renotify_s: fields.renotify_s ?? null });
      state().rules.push(created);
      return HttpResponse.json(created, { status: 201 });
    }),
    http.patch(`${API}/admin/alerts/rules/:ruleId`, async ({ request, params }) => {
      const body = (await request.json()) as AlertRulePatch;
      const denied = guard(request, body);
      if (denied) return denied;
      const r = find(params.ruleId);
      if (!r) return notFound();
      const changes = withoutReason(body);
      if (changes.name && r.is_default && changes.name !== r.name) {
        return HttpResponse.json({ detail: "A default rule keeps its name" }, { status: 409 });
      }
      Object.assign(r, changes, { updated_at: new Date().toISOString() });
      if (changes.enabled === false) r.state = "ok";
      return HttpResponse.json(r);
    }),
    http.delete(`${API}/admin/alerts/rules/:ruleId`, async ({ request, params }) => {
      const body = (await request.json()) as { reason?: string };
      const denied = guard(request, body);
      if (denied) return denied;
      const r = find(params.ruleId);
      if (!r) return notFound();
      if (r.is_default || DEFAULT_NAMES.has(r.name)) {
        return HttpResponse.json({ detail: "Default rules cannot be deleted. Disable the rule instead." }, { status: 409 });
      }
      state().rules = state().rules.filter((x) => x.id !== r.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${API}/admin/alerts/rules/:ruleId/mute`, async ({ request, params }) => {
      const body = (await request.json()) as { until: string | null; reason?: string };
      const denied = guard(request, body);
      if (denied) return denied;
      const r = find(params.ruleId);
      if (!r) return notFound();
      r.muted_until = body.until;
      return HttpResponse.json(r);
    }),
    http.post(`${API}/admin/alerts/rules/:ruleId/test`, async ({ request, params }) => {
      const body = (await request.json()) as { reason?: string };
      const denied = guard(request, body);
      if (denied) return denied;
      const r = find(params.ruleId);
      if (!r) return notFound();
      const event: AlertEvent = {
        id: newId(),
        rule_id: r.id,
        rule_name: r.name,
        severity: r.severity,
        kind: "test",
        value: r.last_value,
        at: new Date().toISOString(),
        notified: true,
        notify_error: null,
      };
      state().events.unshift(event);
      return HttpResponse.json({ sent: true, error: null, event });
    }),
    http.get(`${API}/admin/alerts/events`, ({ request }) => {
      if (!admin()) return notFound();
      const q = new URL(request.url).searchParams;
      const ruleId = q.get("rule_id");
      const kind = q.get("kind");
      const since = q.get("since");
      const events = state()
        .events.filter((e) => !ruleId || e.rule_id === ruleId)
        .filter((e) => !kind || e.kind === kind)
        .filter((e) => !since || Date.parse(e.at) >= Date.parse(since))
        .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
      return HttpResponse.json(events);
    }),
  ];
}
