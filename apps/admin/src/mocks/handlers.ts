/**
 * MSW handlers for the admin sign-in routes (AA-2, AA-3) and /health, with the same paths and
 * shapes as openapi.json. Admins are `db.admins` (admin@example.com by default, like an
 * ADMIN_EMAILS seed); they sign in with their account's password (`db.passwords`) or an email
 * link. `db.signedIn` is this browser's admin session, the mock of the sh_admin cookie.
 */
import { http, HttpResponse } from "msw/http";

import type { AdminLinkSent, AdminMe, AdminProviders, Health } from "../api/types";
import { newId, type MockAdmin, type MockDb, type MockStore } from "./db";

export const API = "*/api";

const HOUR_MS = 3_600_000;
const LINK_PREFIX = "mock-link:";

/** The active admin with this email, or null. */
export function activeAdmin(db: MockDb, email: string): MockAdmin | null {
  const wanted = email.trim().toLowerCase();
  return db.admins.find((a) => a.email === wanted && !a.disabled_at) ?? null;
}

/** The admin of this browser's live session, or null (the API's 404 / 401 case). */
export function currentAdmin(db: MockDb): MockAdmin | null {
  const session = db.adminSessions.find((s) => s.id === db.signedIn && !s.revoked);
  return session ? activeAdmin(db, session.email) : null;
}

export function currentSessionId(db: MockDb): string | null {
  return currentAdmin(db) ? db.signedIn : null;
}

export function authHandlers(store: MockStore) {
  const me = (): AdminMe | null => {
    const admin = currentAdmin(store.db);
    const session = store.db.adminSessions.find((s) => s.id === store.db.signedIn);
    if (!admin || !session) return null;
    return { id: admin.id, email: admin.email, session_expires_at: session.expires_at };
  };

  const startSession = (admin: MockAdmin) => {
    openSession(store, admin);
    return HttpResponse.json(me());
  };

  return [
    http.get(`${API}/health`, () => {
      const body: Health = { status: "ok", version: "0.0.0-mock", model_profile: "fake", checks: {} };
      return HttpResponse.json(body);
    }),
    http.get(`${API}/admin/auth/providers`, () => {
      const body: AdminProviders = { google: true, email: true, password: true };
      return HttpResponse.json(body);
    }),
    http.get(`${API}/admin/me`, () => {
      const body = me();
      return body ? HttpResponse.json(body) : HttpResponse.json({ detail: "Sign in first" }, { status: 401 });
    }),
    http.post(`${API}/admin/auth/password`, async ({ request }) => {
      const body = (await request.json()) as { email: string; password: string };
      const email = body.email.trim().toLowerCase();
      const admin = activeAdmin(store.db, email);
      if (!admin || store.db.passwords[email] !== body.password) {
        return HttpResponse.json({ detail: "The email or password is wrong." }, { status: 401 });
      }
      return startSession(admin);
    }),
    http.post(`${API}/admin/auth/link`, async ({ request }) => {
      const body = (await request.json()) as { email?: string };
      if (!body.email || !body.email.includes("@")) {
        return HttpResponse.json({ detail: [{ msg: "value is not a valid email address" }] }, { status: 422 });
      }
      const sent: AdminLinkSent = { sent: true, dev_link: null };
      return HttpResponse.json(sent, { status: 202 });
    }),
    http.post(`${API}/admin/auth/link/verify`, async ({ request }) => {
      // In the mock a token is "mock-link:<email>".
      const { token } = (await request.json()) as { token: string };
      const admin = token.startsWith(LINK_PREFIX) ? activeAdmin(store.db, token.slice(LINK_PREFIX.length)) : null;
      if (!admin) return HttpResponse.json({ detail: "link_invalid" }, { status: 400 });
      return startSession(admin);
    }),
    http.post(`${API}/admin/auth/signout`, () => {
      const session = store.db.adminSessions.find((s) => s.id === store.db.signedIn);
      if (session) session.revoked = true;
      store.db.signedIn = null;
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}

function openSession(store: MockStore, admin: MockAdmin): void {
  const now = Date.now();
  const id = `${newId().replace(/-/g, "")}${newId().replace(/-/g, "")}`;
  store.db.adminSessions.push({
    id,
    email: admin.email,
    created_at: new Date(now).toISOString(),
    last_seen_at: new Date(now).toISOString(),
    expires_at: new Date(now + 12 * HOUR_MS).toISOString(),
    ip: "127.0.0.1",
    user_agent: "Mock browser",
    revoked: false,
  });
  store.db.signedIn = id;
  store.save();
}

/** Sign the mock browser in as an admin, for tests that start on an admin page. */
export function mockSignIn(store: MockStore, email: string): void {
  const admin = activeAdmin(store.db, email);
  if (!admin) throw new Error(`${email} is not a mock admin`);
  openSession(store, admin);
}

/** The token the mock accepts at /admin/auth/link/verify. */
export function mockLinkToken(email: string): string {
  return `${LINK_PREFIX}${email}`;
}
