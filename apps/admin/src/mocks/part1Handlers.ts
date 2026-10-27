/**
 * MSW handlers for v2 Part 1 (S16): the tone and difficulty mix (AD-3) and the auto-profile
 * queue (AP-3), with the shapes in openapi.json. Writes need `X-Admin-Request: 1` and a reason.
 */
import { http, HttpResponse } from "msw/http";

import type { AdminAutoProfile, AdminAutoProfiles, AutoProfileStatus, Part1Usage } from "../api/part1";
import { currentAdmin, API } from "./handlers";
import type { MockStore } from "./db";

const NOT_MEASURED = {
  measured: false,
  value: null,
  previous: null,
  unit: "count" as const,
  target: null,
  reason: "No plan page event is recorded yet: the app has no product-event store.",
  note: null,
  link: null,
};

export const MOCK_PART1_USAGE: Part1Usage = {
  weeks: [
    {
      week_start: "2026-10-19T00:00:00Z",
      sessions: 4,
      tone: { as_company: 4, warm: 0, neutral: 0, direct: 0 },
      difficulty: { friendly: 1, realistic: 3, tough: 0 },
    },
    {
      week_start: "2026-10-26T00:00:00Z",
      sessions: 5,
      tone: { as_company: 2, warm: 1, neutral: 0, direct: 2 },
      difficulty: { friendly: 0, realistic: 3, tough: 2 },
    },
  ],
  tone: { as_company: 6, warm: 1, neutral: 0, direct: 2 },
  difficulty: { friendly: 1, realistic: 6, tough: 2 },
  plan_page_views: NOT_MEASURED,
  plan_sessions: NOT_MEASURED,
};

function profile(n: number, company: string, status: AutoProfileStatus, created: string): AdminAutoProfile {
  const host = `${company.toLowerCase()}.example`;
  return {
    id: `00000000-0000-4000-8000-0000000000c${n}`,
    company_name: company,
    normalized_name: company.toLowerCase(),
    source_host: host,
    summary: `${company} builds developer tools and hires engineers who like hard problems.`,
    values_mentioned: ["Ship it", "Own it"],
    interview_process_notes: ["Two technical rounds"],
    sources: [`https://${host}/about`, `https://${host}/careers`],
    status,
    reviewed_by: status === "pending" ? null : "admin@example.com",
    reviewed_at: status === "pending" ? null : "2026-10-26T10:00:00Z",
    model_profile: "fake",
    prompt_version: "extractor/auto_profile.v1",
    created_at: created,
  };
}

export const MOCK_AUTO_PROFILES: AdminAutoProfile[] = [
  profile(1, "Acme", "pending", "2026-10-25T10:00:00Z"),
  profile(2, "Globex", "pending", "2026-10-26T09:00:00Z"),
  profile(3, "Initech", "approved", "2026-10-20T09:00:00Z"),
];

export function part1Handlers(store: MockStore) {
  let rows: AdminAutoProfile[] = structuredClone(MOCK_AUTO_PROFILES);
  let seen = store.db;
  /** A store reset gives a fresh database: start the queue over with it. */
  const current = () => {
    if (seen !== store.db) {
      seen = store.db;
      rows = structuredClone(MOCK_AUTO_PROFILES);
    }
    return rows;
  };
  const notFound = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 });
  const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 });

  /** The AA-5/AA-6 checks and the row; a Response when the request is refused. */
  async function write(
    request: Request,
    id: string,
  ): Promise<{ row: AdminAutoProfile; body: { reason: string; summary?: string } } | Response> {
    if (!currentAdmin(store.db)) return notFound();
    if (request.headers.get("X-Admin-Request") !== "1") {
      return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
    }
    const body = (await request.json()) as { reason: string; summary?: string };
    if (!body.reason || body.reason.trim().length < 3) {
      return HttpResponse.json({ detail: "reason is required" }, { status: 422 });
    }
    const row = current().find((r) => r.id === id);
    return row ? { row, body } : notFound();
  }

  const reviewed = (row: AdminAutoProfile) => {
    row.reviewed_by = currentAdmin(store.db)?.email ?? null;
    row.reviewed_at = new Date().toISOString();
  };

  return [
    http.get(`${API}/admin/part1/usage`, () =>
      currentAdmin(store.db) ? HttpResponse.json(MOCK_PART1_USAGE) : notFound(),
    ),
    http.get(`${API}/admin/auto-profiles`, ({ request }) => {
      if (!currentAdmin(store.db)) return notFound();
      const status = new URL(request.url).searchParams.get("status") ?? "pending";
      const all = current();
      const out: AdminAutoProfiles = {
        counts: {
          pending: all.filter((r) => r.status === "pending").length,
          approved: all.filter((r) => r.status === "approved").length,
          retired: all.filter((r) => r.status === "retired").length,
        },
        profiles: all
          .filter((r) => status === "all" || r.status === status)
          .sort((a, b) => a.created_at.localeCompare(b.created_at)),
      };
      return HttpResponse.json(out);
    }),
    http.post(`${API}/admin/auto-profiles/:id/approve`, async ({ request, params }) => {
      const got = await write(request, String(params.id));
      if (got instanceof Response) return got;
      if (got.row.status !== "pending") return conflict(`The profile is ${got.row.status}`);
      got.row.status = "approved";
      reviewed(got.row);
      return HttpResponse.json(got.row);
    }),
    http.put(`${API}/admin/auto-profiles/:id/summary`, async ({ request, params }) => {
      const got = await write(request, String(params.id));
      if (got instanceof Response) return got;
      if (got.row.status === "retired") return conflict("A retired profile cannot be edited");
      const text = (got.body.summary ?? "").trim();
      if (!text) return HttpResponse.json({ detail: "summary is required" }, { status: 422 });
      got.row.summary = text;
      reviewed(got.row);
      return HttpResponse.json(got.row);
    }),
    http.post(`${API}/admin/auto-profiles/:id/retire`, async ({ request, params }) => {
      const got = await write(request, String(params.id));
      if (got instanceof Response) return got;
      if (got.row.status === "retired") return conflict("The profile is already retired");
      got.row.status = "retired";
      reviewed(got.row);
      return HttpResponse.json(got.row);
    }),
  ];
}
