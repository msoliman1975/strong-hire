/**
 * MSW handlers for Settings (AA-1, AA-8): admins and my admin sessions, with the same paths and
 * shapes as openapi.json. Writes need `X-Admin-Request: 1` (AA-5) and a reason (AA-6), and add an
 * audit entry, like the real API.
 */
import { http, HttpResponse } from "msw/http";

import type { AdminAccount, AdminSignInSession } from "../api/types";
import { auditLog } from "./adminHandlers";
import { newId, type MockAdmin, type MockStore } from "./db";
import { API, currentAdmin } from "./handlers";

const IDLE_MS = 2 * 3_600_000;

function notFound() {
  return HttpResponse.json({ detail: "Not Found" }, { status: 404 });
}

function writeRefused(request: Request) {
  return request.headers.get("X-Admin-Request") === "1"
    ? null
    : HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
}

function badReason(reason: unknown) {
  return typeof reason !== "string" || reason.trim().length < 3
    ? HttpResponse.json({ detail: [{ msg: "String should have at least 3 characters" }] }, { status: 422 })
    : null;
}

export function settingsHandlers(store: MockStore) {
  const db = () => store.db;
  const live = (email: string) => db().adminSessions.filter((s) => s.email === email && !s.revoked);
  const account = (a: MockAdmin): AdminAccount => ({ ...a, live_sessions: a.disabled_at ? 0 : live(a.email).length });
  const audit = (actor: string, action: string, entity: string, details: Record<string, unknown>) =>
    auditLog(db()).unshift({ id: newId(), at: new Date().toISOString(), actor, action, entity, org_id: null, details });

  return [
    http.get(`${API}/admin/admins`, () => {
      if (!currentAdmin(db())) return notFound();
      const rows = [...db().admins].sort(
        (a, b) => Number(Boolean(a.disabled_at)) - Number(Boolean(b.disabled_at)) || a.email.localeCompare(b.email),
      );
      return HttpResponse.json(rows.map(account));
    }),

    http.post(`${API}/admin/admins`, async ({ request }) => {
      const me = currentAdmin(db());
      if (!me) return notFound();
      const refused = writeRefused(request);
      if (refused) return refused;
      const body = (await request.json()) as { email?: string; reason?: string };
      const invalid = badReason(body.reason);
      if (invalid) return invalid;
      const email = (body.email ?? "").trim().toLowerCase();
      if (!email.includes("@")) {
        return HttpResponse.json({ detail: [{ msg: "value is not a valid email address" }] }, { status: 422 });
      }
      let row = db().admins.find((a) => a.email === email);
      if (row && !row.disabled_at) {
        return HttpResponse.json({ detail: "That email is already an admin." }, { status: 409 });
      }
      if (row) {
        row.disabled_at = null;
        row.added_by = me.email;
      } else {
        row = { id: newId(), email, added_by: me.email, added_at: new Date().toISOString(), disabled_at: null };
        db().admins.push(row);
      }
      audit(me.email, "admin.admin_added", `admin_user:${row.id}`, {
        reason: body.reason,
        before: null,
        after: { email, active: true },
      });
      store.save();
      return HttpResponse.json(account(row), { status: 201 });
    }),

    http.delete(`${API}/admin/admins/:adminId`, async ({ request, params }) => {
      const me = currentAdmin(db());
      if (!me) return notFound();
      const refused = writeRefused(request);
      if (refused) return refused;
      const body = (await request.json()) as { reason?: string };
      const invalid = badReason(body.reason);
      if (invalid) return invalid;
      const row = db().admins.find((a) => a.id === params.adminId);
      if (!row) return HttpResponse.json({ detail: "No such admin" }, { status: 404 });
      if (row.id === me.id) return HttpResponse.json({ detail: "You cannot remove yourself." }, { status: 409 });
      if (row.disabled_at) return HttpResponse.json({ detail: "That admin was already removed." }, { status: 409 });
      const sessions = live(row.email);
      sessions.forEach((s) => (s.revoked = true));
      row.disabled_at = new Date().toISOString();
      audit(me.email, "admin.admin_removed", `admin_user:${row.id}`, {
        reason: body.reason,
        before: { email: row.email, active: true },
        after: { email: row.email, active: false },
        sessions_revoked: sessions.length,
      });
      store.save();
      return HttpResponse.json(account(row));
    }),

    http.get(`${API}/admin/me/sessions`, () => {
      const me = currentAdmin(db());
      if (!me) return notFound();
      const rows: AdminSignInSession[] = live(me.email)
        .map((s) => ({
          id: s.id,
          created_at: s.created_at,
          last_seen_at: s.last_seen_at,
          expires_at: s.expires_at,
          ends_at: new Date(Math.min(Date.parse(s.expires_at), Date.parse(s.last_seen_at) + IDLE_MS)).toISOString(),
          ip: s.ip,
          user_agent: s.user_agent,
          current: s.id === db().signedIn,
        }))
        .reverse();
      return HttpResponse.json(rows);
    }),

    http.delete(`${API}/admin/me/sessions/:sessionId`, ({ request, params }) => {
      const me = currentAdmin(db());
      if (!me) return notFound();
      const refused = writeRefused(request);
      if (refused) return refused;
      const session = live(me.email).find((s) => s.id === params.sessionId);
      if (!session) return HttpResponse.json({ detail: "No such session" }, { status: 404 });
      session.revoked = true;
      if (session.id === db().signedIn) db().signedIn = null;
      audit(me.email, "admin.session_revoked", `admin_session:${session.id.slice(0, 12)}`, {
        reason: "Revoked my own session",
      });
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}
