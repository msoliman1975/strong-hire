/**
 * MSW handlers for the public waitlist (L04 step 1), with the shapes in openapi.json. Like the
 * API, a join always answers "check_email". In the mock, the token "valid" confirms.
 */
import { http, HttpResponse } from "msw/http";

const API = "*/api";

export function waitlistHandlers() {
  return [
    http.post(`${API}/public/waitlist`, () => HttpResponse.json({ status: "check_email" }, { status: 202 })),
    http.post(`${API}/public/waitlist/confirm`, async ({ request }) => {
      const { token } = (await request.json()) as { token: string };
      return token === "valid"
        ? HttpResponse.json({ status: "confirmed" })
        : HttpResponse.json({ detail: "invalid_link" }, { status: 400 });
    }),
  ];
}
