/** MSW handler for the admin Waitlist page (L04), with the shapes in openapi.json. */
import { http, HttpResponse } from "msw/http";

import type { AdminWaitlist } from "../api/waitlist";
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
  return [
    http.get(`${API}/admin/waitlist`, () =>
      currentAdmin(store.db) ? HttpResponse.json(MOCK_WAITLIST) : HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
    ),
  ];
}
