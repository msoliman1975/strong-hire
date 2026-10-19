/**
 * MSW handlers for Operations → Controls (OC-1 to OC-6), with the same paths and shapes as
 * openapi.json. Only admin@example.com gets answers; everyone else gets 404, like the real API.
 * The settings live per mock database, so a store reset puts every control back to its default.
 */
import { http, HttpResponse } from "msw/http";

import type { ModelProfile, OpsSettings, RuntimeSettings, SettingKey } from "../api/controls";
import type { MockDb, MockStore } from "./db";
import { API, isMockAdmin } from "./handlers";

export const MOCK_DEFAULTS: RuntimeSettings = {
  signups_paused: false,
  sessions_paused_voice: false,
  sessions_paused_text: false,
  daily_spend_cap_usd: 25,
  site_banner: null,
  jobs_paused: [],
  sim_paused: false,
  sim_max_live_sessions: 3,
};

const KEYS = Object.keys(MOCK_DEFAULTS) as SettingKey[];

interface OpsState {
  values: RuntimeSettings;
  meta: Partial<Record<SettingKey, { updated_by: string; updated_at: string }>>;
  spendTodayUsd: number;
  models: ModelProfile;
}

const MOCK_MODELS: ModelProfile = {
  api_profile: "fake",
  roles: ["extractor", "planner", "interviewer", "scorer", "stt", "tts", "candidate", "judge"].map((role) => ({
    role,
    alias: `fake-${role}`,
    kind: ["stt", "tts"].includes(role) ? role : "chat",
    tier: null,
    test_only: role === "candidate" || role === "judge",
  })),
  services: [],
  heartbeats_available: true,
  mismatch: false,
};

const states = new WeakMap<MockDb, OpsState>();

/** The mock ops state of a store, for tests that want to set spend or heartbeats. */
export function opsState(db: MockDb): OpsState {
  let state = states.get(db);
  if (!state) {
    state = {
      values: { ...MOCK_DEFAULTS, jobs_paused: [] },
      meta: {},
      spendTodayUsd: 3.21,
      models: structuredClone(MOCK_MODELS),
    };
    states.set(db, state);
  }
  return state;
}

function view(state: OpsState): OpsSettings {
  return {
    values: state.values,
    defaults: MOCK_DEFAULTS,
    meta: KEYS.map((key) => ({
      key,
      is_default: JSON.stringify(state.values[key]) === JSON.stringify(MOCK_DEFAULTS[key]),
      updated_by: state.meta[key]?.updated_by ?? null,
      updated_at: state.meta[key]?.updated_at ?? null,
    })),
    spend_today_usd: state.spendTodayUsd,
  };
}

function invalid(msg: string) {
  return HttpResponse.json({ detail: `Invalid value: ${msg}` }, { status: 422 });
}

function check(key: SettingKey, value: unknown): string | null {
  switch (key) {
    case "daily_spend_cap_usd":
      return typeof value === "number" && value >= 0 ? null : "must be a number of 0 or more";
    case "site_banner": {
      if (value === null) return null;
      const b = value as { text?: unknown; severity?: unknown; until?: unknown };
      if (typeof b.text !== "string" || !b.text) return "text is required";
      if (!["info", "warning", "critical"].includes(String(b.severity))) return "bad severity";
      if (typeof b.until !== "string" || Number.isNaN(Date.parse(b.until))) return "bad until";
      return null;
    }
    case "sim_max_live_sessions":
      return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 20
        ? null
        : "must be a whole number from 0 to 20";
    case "jobs_paused":
      return Array.isArray(value) && value.every((v) => v === "gap_analysis" || v === "scoring")
        ? null
        : "unknown job kind";
    default:
      return typeof value === "boolean" ? null : "must be true or false";
  }
}

export function controlsHandlers(store: MockStore) {
  const admin = () => {
    const { auth } = store.db;
    return auth.status === "signed_in" && auth.userEmail && isMockAdmin(auth.userEmail) ? auth.userEmail : null;
  };
  const notFound = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 });

  return [
    http.get(`${API}/admin/ops/settings`, () => (admin() ? HttpResponse.json(view(opsState(store.db))) : notFound())),
    http.get(`${API}/admin/ops/models`, () => (admin() ? HttpResponse.json(opsState(store.db).models) : notFound())),
    http.put(`${API}/admin/ops/settings/:key`, async ({ params, request }) => {
      const who = admin();
      if (!who) return notFound();
      if (request.headers.get("X-Admin-Request") !== "1") {
        return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      }
      const key = String(params.key) as SettingKey;
      if (!KEYS.includes(key)) return HttpResponse.json({ detail: `No setting '${key}'` }, { status: 404 });
      const body = (await request.json()) as { value?: unknown; reason?: string };
      if (!body.reason || body.reason.trim().length < 3) {
        return HttpResponse.json({ detail: [{ msg: "reason: at least 3 characters" }] }, { status: 422 });
      }
      const problem = check(key, body.value);
      if (problem) return invalid(problem);
      const state = opsState(store.db);
      let value = body.value;
      if (key === "jobs_paused") value = [...new Set(value as string[])].sort();
      state.values = { ...state.values, [key]: value } as RuntimeSettings;
      state.meta[key] = { updated_by: who, updated_at: new Date().toISOString() };
      return HttpResponse.json(view(state));
    }),
  ];
}
