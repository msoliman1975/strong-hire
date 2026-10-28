/**
 * MSW handlers for v2 Part 2 (S25): story library metrics (AD-4), with the shape in openapi.json.
 * Aggregate only, like the API: no story text.
 */
import { http, HttpResponse } from "msw/http";

import type { Part2Stories } from "../api/part2";
import { currentAdmin, API } from "./handlers";
import type { MockStore } from "./db";

export const MOCK_PART2_STORIES: Part2Stories = {
  story_save_rate: {
    measured: true,
    value: 0.375,
    previous: null,
    unit: "pct",
    target: 0.4,
    reason: null,
    note: "Users whose first debrief is at least 30 days old.",
    link: null,
  },
  stories_per_user: {
    measured: true,
    value: 2.5,
    previous: null,
    unit: "ratio",
    target: null,
    reason: null,
    note: "Stories per user who saved at least one.",
    link: null,
  },
  draft_to_proven_rate: {
    measured: true,
    value: 0.2,
    previous: null,
    unit: "pct",
    target: null,
    reason: null,
    note: "Proven stories as a share of all stories (ST-7).",
    link: null,
  },
  save_cohort: { users: 8, saved: 3 },
  counts: {
    total: 10,
    draft: 8,
    proven: 2,
    by_source: { debrief_answer: 6, manual: 3, coach: 1 },
    users_with_stories: 4,
  },
  stories_by_week: [
    { week_start: "2026-10-19T00:00:00Z", saved: 4 },
    { week_start: "2026-10-26T00:00:00Z", saved: 6 },
  ],
  delivery: [
    {
      week_start: "2026-10-19T00:00:00Z",
      answers: 12,
      words_per_minute: 148.2,
      fillers_per_minute: 3.4,
      duration_seconds: 74.5,
    },
    {
      week_start: "2026-10-26T00:00:00Z",
      answers: 0,
      words_per_minute: null,
      fillers_per_minute: null,
      duration_seconds: null,
    },
  ],
};

export function part2Handlers(store: MockStore) {
  return [
    http.get(`${API}/admin/part2/stories`, () =>
      currentAdmin(store.db)
        ? HttpResponse.json(MOCK_PART2_STORIES)
        : HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
    ),
  ];
}
