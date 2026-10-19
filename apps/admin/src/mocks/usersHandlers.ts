/**
 * MSW handlers for Users and support (AU-1..AU-10), with the same paths and shapes as
 * openapi.json. Grants, suspension and the session epoch live in a side table per mock database.
 * Writes need `X-Admin-Request: 1` and a reason, and add audit entries, like the real API.
 */
import { http, HttpResponse } from "msw/http";

import type { AdminAuditEntry } from "../api/admin";
import type { AdminGrant, AdminUser, AdminUserDetail, AdminUserPage, GrantKind } from "../api/users";
import type { AuthUser } from "../api/types";
import { auditLog } from "./adminHandlers";
import { newId, type MockDb, type MockStore } from "./db";
import { activeAdmin, API, currentAdmin } from "./handlers";

interface UserState {
  grants: AdminGrant[];
  suspendedAt: string | null;
  suspendedReason: string | null;
  epoch: number;
  linksSent: number;
}

const states = new WeakMap<MockDb, Record<string, UserState>>();

function stateOf(db: MockDb, userId: string): UserState {
  let all = states.get(db);
  if (!all) {
    all = {};
    states.set(db, all);
  }
  all[userId] ??= { grants: [], suspendedAt: null, suspendedReason: null, epoch: 0, linksSent: 0 };
  return all[userId];
}

const json = (detail: string, status: number) => HttpResponse.json({ detail }, { status });

function active(g: AdminGrant): boolean {
  return !g.revoked_at && (!g.expires_at || Date.parse(g.expires_at) > Date.now());
}

export function usersHandlers(store: MockStore) {
  const db = () => store.db;
  const admin = () => currentAdmin(db());
  const byId = (id: unknown) => Object.values(db().users).find((u) => u.id === id);
  const sessionsOf = (u: AuthUser) => (activeAdmin(db(), u.email) !== null ? 0 : db().sessions.length);

  const entitlement = (u: AuthUser) => {
    const st = stateOf(db(), u.id);
    const live = st.grants.filter(active);
    const sum = (kind: GrantKind) => live.filter((g) => g.kind === kind).reduce((n, g) => n + g.amount, 0);
    const comp = live.filter((g) => g.kind === "comp_plan").sort((a, b) => b.amount - a.amount)[0];
    const usage = db().usage;
    const subPaid = usage.plan === "paid";
    const paid = subPaid || Boolean(comp);
    const planCap = Math.max(subPaid ? usage.minutes_cap : 0, comp?.amount ?? 0);
    const granted = paid ? sum("minutes") : 0;
    const used = subPaid ? usage.minutes_used : 0;
    const cap = paid ? Math.max(0, planCap + granted) : 0;
    const freeTotal = usage.free_interviews_total + sum("free_interviews");
    const freeUsed = sessionsOf(u);
    return {
      plan: paid ? ("paid" as const) : ("free" as const),
      minutes_used: used,
      plan_minutes_cap: planCap,
      minutes_granted: granted,
      minutes_cap: cap,
      minutes_left: paid ? Math.max(0, cap - used) : 0,
      free_interviews_total: freeTotal,
      free_interviews_granted: sum("free_interviews"),
      free_interviews_used: freeUsed,
      free_interviews_left: Math.max(0, freeTotal - freeUsed),
      comp_until: comp?.expires_at ?? null,
      block_code: null,
    };
  };

  const row = (u: AuthUser): AdminUser => {
    const st = stateOf(db(), u.id);
    const ent = entitlement(u);
    return {
      id: u.id,
      email: u.email,
      full_name: u.full_name ?? null,
      auth_provider: u.auth_provider,
      created_at: u.created_at,
      last_sign_in_at: u.created_at,
      plan: ent.plan,
      subscription_status: db().usage.status,
      comp_until: ent.comp_until,
      minutes_used: ent.minutes_used,
      minutes_cap: ent.minutes_cap,
      minutes_left: ent.minutes_left,
      free_interviews_left: ent.free_interviews_left,
      training_consent: u.training_consent,
      interviews: sessionsOf(u),
      is_admin: activeAdmin(db(), u.email) !== null,
      status: st.suspendedAt ? "suspended" : "active",
      suspended_at: st.suspendedAt,
    };
  };

  const audit = (me: { email: string }, u: AuthUser, action: string, reason: string, extra: Record<string, unknown> = {}) => {
    const entry: AdminAuditEntry = {
      id: newId(),
      at: new Date().toISOString(),
      actor: me.email,
      action,
      entity: `user:${u.id}`,
      org_id: u.org_id,
      details: { reason, ...extra },
    };
    auditLog(db()).unshift(entry);
  };

  /** The admin, the target user and the reason of a write, or an error response. */
  const write = async (request: Request, userId: unknown) => {
    const me = admin();
    if (!me) return { error: json("Not Found", 404) };
    if (request.headers.get("X-Admin-Request") !== "1") return { error: json("X-Admin-Request: 1 is required", 403) };
    const user = byId(userId);
    if (!user) return { error: json("User not found", 404) };
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const reason = typeof body.reason === "string" ? body.reason.trim() : "";
    if (reason.length < 3) return { error: HttpResponse.json({ detail: [{ msg: "reason is too short" }] }, { status: 422 }) };
    return { me, user, body, reason };
  };

  return [
    http.get(`${API}/admin/users`, ({ request }) => {
      if (!admin()) return json("Not Found", 404);
      const p = new URL(request.url).searchParams;
      const q = (p.get("q") ?? "").trim().toLowerCase();
      const page = Math.max(1, Number(p.get("page") ?? "1"));
      const size = Math.min(200, Math.max(1, Number(p.get("page_size") ?? "50")));
      const day = (iso: string) => iso.slice(0, 10);
      const all = Object.values(db().users)
        .map(row)
        .filter((u) => !q || u.id === q || u.email.includes(q) || (u.full_name ?? "").toLowerCase().includes(q))
        .filter((u) => !p.get("plan") || u.plan === p.get("plan"))
        .filter((u) => !p.get("status") || u.status === p.get("status"))
        .filter((u) => !p.get("signed_up_from") || day(u.created_at) >= (p.get("signed_up_from") ?? ""))
        .filter((u) => !p.get("signed_up_to") || day(u.created_at) <= (p.get("signed_up_to") ?? ""))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      const body: AdminUserPage = {
        users: all.slice((page - 1) * size, page * size),
        total: all.length,
        page,
        page_size: size,
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/admin/users/:userId`, ({ params }) => {
      if (!admin()) return json("Not Found", 404);
      const u = byId(params.userId);
      if (!u) return json("User not found", 404);
      const st = stateOf(db(), u.id);
      const entries = auditLog(db()).filter((a) => a.entity === `user:${u.id}` || a.org_id === u.org_id);
      const body: AdminUserDetail = {
        user: row(u),
        profile: {
          full_name: u.full_name ?? null,
          current_title: null,
          years_experience: null,
          target_level: null,
          country: null,
          time_zone: null,
          linkedin_url: null,
          profile_completed_at: u.created_at,
          email_verified_at: u.created_at,
          has_password: u.auth_provider === "password",
        },
        org: { id: u.org_id, name: u.email, type: "personal", plan: db().usage.plan, created_at: u.created_at },
        suspended_reason: st.suspendedReason,
        session_epoch: st.epoch,
        subscription: null,
        entitlement: entitlement(u),
        grants: [...st.grants].reverse().map((g) => ({ ...g, active: active(g) })),
        sessions: [],
        job_targets: [],
        resume_count: 0,
        resumes: [],
        gap_analysis_count: 0,
        gap_analyses: [],
        cost_to_date_usd: 0,
        cost_unknown_events: 0,
        refunds: [],
        privacy_actions: entries.filter((a) => a.action.startsWith("account.")),
        audit: entries,
      };
      return HttpResponse.json(body);
    }),

    http.post(`${API}/admin/users/:userId/grants`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const kind = w.body.kind as GrantKind;
      const amount = Number(w.body.amount);
      const expires = typeof w.body.expires_at === "string" ? w.body.expires_at : null;
      if (!Number.isInteger(amount) || amount === 0 || (kind === "comp_plan" && !expires)) {
        return HttpResponse.json({ detail: [{ msg: "invalid grant" }] }, { status: 422 });
      }
      const grant: AdminGrant = {
        id: newId(),
        kind,
        amount,
        expires_at: expires,
        reason: w.reason,
        granted_by: w.me.email,
        created_at: new Date().toISOString(),
        revoked_at: null,
        revoked_by: null,
        active: true,
      };
      stateOf(db(), w.user.id).grants.push(grant);
      audit(w.me, w.user, `user.grant_added.${kind}`, w.reason, { after: { kind, amount, expires_at: expires } });
      return HttpResponse.json(grant, { status: 201 });
    }),

    http.delete(`${API}/admin/users/:userId/grants/:grantId`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const grant = stateOf(db(), w.user.id).grants.find((g) => g.id === params.grantId);
      if (!grant) return json("Grant not found", 404);
      if (grant.revoked_at) return json("The grant was already revoked", 409);
      grant.revoked_at = new Date().toISOString();
      grant.revoked_by = w.me.email;
      audit(w.me, w.user, `user.grant_revoked.${grant.kind}`, w.reason);
      return HttpResponse.json({ ...grant, active: false });
    }),

    http.post(`${API}/admin/users/:userId/suspend`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const st = stateOf(db(), w.user.id);
      if (st.suspendedAt) return json("The user is already suspended", 409);
      if (activeAdmin(db(), w.user.email) !== null) return json("Remove the admin access first", 409);
      st.suspendedAt = new Date().toISOString();
      st.suspendedReason = w.reason;
      audit(w.me, w.user, "user.suspended", w.reason);
      return HttpResponse.json({ action: "user.suspended", user_id: w.user.id, details: { sessions_ended: [] } });
    }),

    http.post(`${API}/admin/users/:userId/unsuspend`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const st = stateOf(db(), w.user.id);
      if (!st.suspendedAt) return json("The user is not suspended", 409);
      st.suspendedAt = null;
      st.suspendedReason = null;
      audit(w.me, w.user, "user.unsuspended", w.reason);
      return HttpResponse.json({ action: "user.unsuspended", user_id: w.user.id, details: {} });
    }),

    http.post(`${API}/admin/users/:userId/signout`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const st = stateOf(db(), w.user.id);
      st.epoch += 1;
      audit(w.me, w.user, "user.signed_out", w.reason);
      return HttpResponse.json({ action: "user.signed_out", user_id: w.user.id, details: { session_epoch: st.epoch } });
    }),

    http.post(`${API}/admin/users/:userId/resend-link`, async ({ request, params }) => {
      const w = await write(request, params.userId);
      if ("error" in w) return w.error;
      const st = stateOf(db(), w.user.id);
      if (st.linksSent >= 3) return json("3 links were sent in the last 15 minutes. Wait, then try again.", 429);
      st.linksSent += 1;
      audit(w.me, w.user, "user.sign_in_link_sent", w.reason);
      return HttpResponse.json({ action: "user.sign_in_link_sent", user_id: w.user.id, details: {} }, { status: 202 });
    }),
  ];
}
