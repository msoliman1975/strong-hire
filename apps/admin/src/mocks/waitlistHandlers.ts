/**
 * MSW handlers for the admin Waitlist page (L04), with the shapes in openapi.json. Invites need
 * `X-Admin-Request: 1` and a reason, go only to confirmed entries and set `invited_at`.
 */
import { http, HttpResponse } from "msw/http";

import type { AdminWaitlist, InviteResult } from "../api/waitlist";
import { currentAdmin, API } from "./handlers";
import type { MockStore } from "./db";
export const MOCK_WAITLIST: AdminWaitlist = {
  total: 2,
  confirmed: 1,
  marketing_consent: 1,
  entries: [
    {
      id: "00000000-0000-4000-8000-0000000000f1",
      email: "ada@example.com",
      interview_within: "two_weeks",
      role_family: "swe",
      marketing_consent: true,
      source: "reddit",
      confirmed_at: "2026-10-25T10:05:00Z",
      invited_at: null,
      created_at: "2026-10-25T10:00:00Z",
    },
    {
      id: "00000000-0000-4000-8000-0000000000f2",
      email: "bo@example.com",
      interview_within: "not_yet",
      role_family: null,
      marketing_consent: false,
      source: null,
      confirmed_at: null,
      invited_at: null,
      created_at: "2026-10-24T09:00:00Z",
    },
  ],
};

export function waitlistHandlers(store: MockStore) {
  let waitlist: AdminWaitlist = structuredClone(MOCK_WAITLIST);
  let seen = store.db;
  /** A store reset gives a fresh database: start the waitlist over with it. */
  const current = () => {
    if (seen !== store.db) {
      seen = store.db;
      waitlist = structuredClone(MOCK_WAITLIST);
    }
    return waitlist;
  };
  const notFound = () => HttpResponse.json({ detail: "Not Found" }, { status: 404 });

  return [
    http.get(`${API}/admin/waitlist`, () => (currentAdmin(store.db) ? HttpResponse.json(current()) : notFound())),
    http.post(`${API}/admin/waitlist/invite`, async ({ request }) => {
      if (!currentAdmin(store.db)) return notFound();
      if (request.headers.get("X-Admin-Request") !== "1") {
        return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      }
      const body = (await request.json()) as { ids: string[]; reason: string };
      if (!body.reason || body.reason.trim().length < 3) {
        return HttpResponse.json({ detail: "reason is required" }, { status: 422 });
      }
      const now = new Date().toISOString();
      const result: InviteResult = { sent: [], skipped: [], failed: [] };
      for (const e of current().entries.filter((x) => body.ids.includes(x.id))) {
        if (e.confirmed_at) {
          e.invited_at = now;
          result.sent.push(e.email);
        } else {
          result.skipped.push(e.email);
        }
      }
      return HttpResponse.json(result);
    }),
  ];
}
