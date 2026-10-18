/**
 * MSW handlers for the sign-in routes and /health the admin app uses, with the same paths and
 * shapes as openapi.json. In the mock, admin@example.com is the admin (ADMIN_EMAILS in the real
 * API); anyone else who signs in is a candidate.
 */
import { http, HttpResponse } from "msw/http";

import type { AuthState, Health } from "../api/types";
import type { MockStore } from "./db";

export const API = "*/api";

export const MOCK_ADMIN_EMAILS = ["admin@example.com"];

export function isMockAdmin(email: string): boolean {
  return MOCK_ADMIN_EMAILS.includes(email.trim().toLowerCase());
}

export function authHandlers(store: MockStore) {
  const state = (): AuthState => {
    const { auth, users } = store.db;
    if (auth.status === "signed_in" && auth.userEmail && users[auth.userEmail]) {
      const user = users[auth.userEmail];
      return { status: "signed_in", email: auth.userEmail, user: { ...user, is_admin: isMockAdmin(user.email) } };
    }
    if (auth.status === "needs_signup") return { status: "needs_signup", email: auth.email, user: null };
    return { status: "signed_out", email: null, user: null };
  };

  const signInAs = (rawEmail: string): AuthState => {
    const email = rawEmail.trim().toLowerCase();
    store.db.auth = store.db.users[email]
      ? { status: "signed_in", email, userEmail: email }
      : { status: "needs_signup", email, userEmail: null };
    store.save();
    return state();
  };

  return [
    http.get(`${API}/health`, () => {
      const body: Health = { status: "ok", version: "0.0.0-mock", model_profile: "fake", checks: {} };
      return HttpResponse.json(body);
    }),
    http.get(`${API}/auth/providers`, () => HttpResponse.json({ google: true, email: true, password: true, dev: false })),
    http.get(`${API}/auth/me`, () => HttpResponse.json(state())),
    http.post(`${API}/auth/dev-login`, async ({ request }) => {
      const body = (await request.json()) as { email?: string };
      return HttpResponse.json(signInAs(body.email ?? "dev@example.com"));
    }),
    http.post(`${API}/auth/magic-link`, async ({ request }) => {
      const body = (await request.json()) as { email?: string };
      if (new URL(request.url).searchParams.get("app") !== "admin") {
        return HttpResponse.json({ detail: "The admin app must ask for app=admin links" }, { status: 400 });
      }
      if (!body.email || !body.email.includes("@")) {
        return HttpResponse.json({ detail: [{ msg: "value is not a valid email address" }] }, { status: 422 });
      }
      return HttpResponse.json({ sent: true, dev_link: null }, { status: 202 });
    }),
    http.post(`${API}/auth/password/login`, async ({ request }) => {
      const body = (await request.json()) as { email: string; password: string };
      const email = body.email.trim().toLowerCase();
      if (!store.db.users[email] || store.db.passwords[email] !== body.password) {
        return HttpResponse.json({ detail: "The email or password is wrong." }, { status: 401 });
      }
      return HttpResponse.json(signInAs(email));
    }),
    http.post(`${API}/auth/logout`, () => {
      store.db.auth = { status: "signed_out", email: null, userEmail: null };
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}
