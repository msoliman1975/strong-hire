/**
 * MSW handlers for v2 Part 3 (S38): coach metrics and readiness by skill (AD-5), with the shape in
 * openapi.json. Aggregate only, like the API: no coach conversation or story text.
 */
import { http, HttpResponse } from "msw/http";

import type { Part3Coach, Part3Readiness } from "../api/part3";
import { currentAdmin, API } from "./handlers";
import type { MockStore } from "./db";

export const MOCK_PART3_COACH: Part3Coach = {
  sessions: 14,
  minutes: 98,
  users: 6,
  by_style: { gentle: 9, direct: 5 },
  by_channel: { voice: 4, text: 10 },
  minutes_per_session: {
    measured: true,
    value: 7,
    previous: null,
    unit: "minutes",
    target: null,
    reason: null,
    note: "Recorded minutes per session.",
    link: null,
  },
  cost_per_session: {
    measured: true,
    value: 0.042,
    previous: null,
    unit: "usd",
    target: null,
    reason: null,
    note: "Usage events with role coach, plus the voice coach's STT and TTS.",
    link: null,
  },
  cost_total_usd: 0.588,
  cap_share: {
    measured: true,
    value: 0.12,
    previous: null,
    unit: "pct",
    target: null,
    reason: null,
    note: "Coach minutes in each paid user's current plan period, as a share of their plan caps.",
    link: null,
  },
  caps: {
    paid_users: 2,
    coach_minutes: 72,
    interview_minutes: 410,
    cap_minutes: 600,
    over_cap_if_counted: 1,
    free_user_coach_minutes: 26,
  },
  weeks: [
    { week_start: "2026-10-19T00:00:00Z", sessions: 5, minutes: 31, voice: 1, text: 4, users: 3 },
    { week_start: "2026-10-26T00:00:00Z", sessions: 9, minutes: 67, voice: 3, text: 6, users: 5 },
  ],
  evals: {
    latest: null,
    runs: [],
    reason: "No coach eval run yet. Run ./scripts/eval.ps1 -Suite coach.",
  },
};

export const MOCK_PART3_READINESS: Part3Readiness = {
  kind: "practice_estimate",
  note: "Practice estimate from Realistic sessions only, last 90 days, without development data.",
  window_days: 90,
  min_sessions: 2,
  users: 7,
  skills: [
    { competency: "ownership", users: 6, users_enough_data: 4, users_at_bar: 3, mean_score: 3.1, sessions: 15 },
    { competency: "impact", users: 6, users_enough_data: 4, users_at_bar: 1, mean_score: 2.4, sessions: 15 },
    { competency: "motivation", users: 2, users_enough_data: 0, users_at_bar: 0, mean_score: null, sessions: 2 },
  ],
};

export function part3Handlers(store: MockStore) {
  const guard = (body: unknown) =>
    currentAdmin(store.db) ? HttpResponse.json(body) : HttpResponse.json({ detail: "Not Found" }, { status: 404 });
  return [
    http.get(`${API}/admin/part3/coach`, () => guard(MOCK_PART3_COACH)),
    http.get(`${API}/admin/part3/readiness`, () => guard(MOCK_PART3_READINESS)),
  ];
}
