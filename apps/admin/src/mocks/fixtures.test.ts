/** Mock payloads must match the real API: each one is validated against openapi.json. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { adminApi } from "../api/admin";
import { alertsApi } from "../api/alerts";
import { authApi } from "../api/auth";
import { controlsApi } from "../api/controls";
import { usersApi } from "../api/users";
import { opsApi } from "../api/ops";
import { mockStore } from "./node";

const OPENAPI = JSON.parse(readFileSync(resolve(__dirname, "../../../web/openapi.json"), "utf8")) as object;

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
ajv.addSchema(OPENAPI, "openapi.json");

function expectApiShape(component: string, payload: unknown) {
  const validate = ajv.compile({ $ref: `openapi.json#/components/schemas/${component}` });
  const ok = validate(payload);
  expect(validate.errors ?? [], `${component} mock does not match openapi.json`).toEqual([]);
  expect(ok).toBe(true);
}

function user(email: string, n: number, consent: boolean) {
  return {
    id: `00000000-0000-4000-8000-0000000000a${n}`,
    org_id: `00000000-0000-4000-8000-0000000000b${n}`,
    email,
    auth_provider: "password" as const,
    training_consent: consent,
    created_at: "2026-10-01T10:00:00Z",
    is_admin: false,
    full_name: null,
    profile_complete: true,
  };
}

describe("admin mocks match openapi.json", () => {
  it("sign-in: providers, me, password login, magic link", async () => {
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    mockStore.db.passwords["admin@example.com"] = "correct horse battery";
    expectApiShape("AuthProviders", await authApi.providers());
    expectApiShape("AuthState", await authApi.me());
    const state = await authApi.passwordLogin({ email: "admin@example.com", password: "correct horse battery" });
    expectApiShape("AuthState", state);
    expect(state.user?.is_admin).toBe(true);
    expectApiShape("MagicLinkSent", await authApi.sendMagicLink("admin@example.com"));
  });

  it("admin: users, interviews, detail with traces, audit (R2)", async () => {
    mockStore.db.users["ana@example.com"] = user("ana@example.com", 1, true);
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    await authApi.devLogin("admin@example.com");
    mockStore.db.sessions.push({
      id: "00000000-0000-4000-8000-0000000000c1",
      job_target_id: "00000000-0000-4000-8000-0000000000d1",
      resume_id: null,
      config: { interview_type: "case", difficulty: "tough", mode: "coach", duration_min: 30, level: "mid" },
      channel: "text",
      brief_ready: true,
      status: "completed",
      started_at: "2026-10-07T09:00:00Z",
      ended_at: "2026-10-07T09:30:00Z",
      minutes_billed: 30,
      failure_reason: null,
    });
    expectApiShape("AdminUserPage", await adminApi.users());
    expectApiShape("AdminSessionList", await adminApi.sessions({ interview_type: "case" }));
    const detail = await adminApi.session("00000000-0000-4000-8000-0000000000c1");
    expectApiShape("AdminSessionDetail", detail);
    expect(detail.traces?.length).toBeGreaterThan(0);
    for (const entry of await adminApi.audit("all")) expectApiShape("AdminAuditEntry", entry);
  });

  it("controls: settings, a change, models (OC-1 to OC-6)", async () => {
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    await authApi.devLogin("admin@example.com");
    expectApiShape("OpsSettings", await controlsApi.settings());
    const banner = { text: "Maintenance", severity: "info" as const, until: "2099-01-01T00:00:00Z" };
    expectApiShape("OpsSettings", await controlsApi.set("site_banner", banner, "planned work"));
    expectApiShape("OpsSettings", await controlsApi.set("jobs_paused", ["scoring"], "provider down"));
    expectApiShape("ModelProfileOut", await controlsApi.models());
  });

  it("alerts: metrics, rules, events, test (AL-1, AL-4, AL-6)", async () => {
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    await authApi.devLogin("admin@example.com");
    for (const m of await alertsApi.metrics()) expectApiShape("AlertMetric", m);
    const rules = await alertsApi.rules();
    for (const r of rules) expectApiShape("AlertRuleOut", r);
    for (const e of await alertsApi.events()) expectApiShape("AlertEventOut", e);
    expectApiShape("AlertTestOut", await alertsApi.test(rules[0].id, "check the inbox"));
  });

  it("users and support (AU-1..AU-9)", async () => {
    mockStore.db.users["ana@example.com"] = user("ana@example.com", 1, true);
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    await authApi.devLogin("admin@example.com");
    const id = "00000000-0000-4000-8000-0000000000a1";
    expectApiShape("AdminUserPage", await usersApi.list({ q: "ana" }));
    const until = new Date(Date.now() + 86_400_000).toISOString();
    const grant = await usersApi.grant(id, { kind: "comp_plan", amount: 120, expires_at: until, reason: "beta tester" });
    expectApiShape("AdminGrant", grant);
    expectApiShape("AdminGrant", await usersApi.revokeGrant(id, grant.id, "ended early"));
    expectApiShape("AdminActionOut", await usersApi.suspend(id, "abuse report"));
    expectApiShape("AdminActionOut", await usersApi.unsuspend(id, "resolved"));
    expectApiShape("AdminActionOut", await usersApi.signOut(id, "lost laptop"));
    expectApiShape("AdminActionOut", await usersApi.resendLink(id, "cannot sign in"));
    expectApiShape("AdminUserDetail", await usersApi.detail(id));
  });

  it("overview and operations (AO, OB-10..OB-14, AI)", async () => {
    mockStore.db.users["admin@example.com"] = user("admin@example.com", 9, false);
    await authApi.devLogin("admin@example.com");
    for (const range of ["24h", "7d", "30d", "90d"] as const) expectApiShape("AdminOverview", await opsApi.overview(range));
    expectApiShape("OpsHealth", await opsApi.health());
    expectApiShape("OpsPerformance", await opsApi.performance("7d"));
    const groups = await opsApi.errors("all");
    for (const g of groups) expectApiShape("OpsErrorGroup", g);
    expectApiShape("OpsErrorDetail", await opsApi.error(groups[0].id));
    expectApiShape("OpsErrorDetail", await opsApi.updateError(groups[0].id, "resolved", "fixed it"));
    const jobs = await opsApi.jobs();
    expectApiShape("OpsJobs", jobs);
    expectApiShape("OpsRetryOut", await opsApi.retry("scoring", jobs.scorings[0].id, "try again"));
    expectApiShape("OpsSpend", await opsApi.spend());
    mockStore.db.sessions.push({
      id: "00000000-0000-4000-8000-0000000000c2",
      job_target_id: "00000000-0000-4000-8000-0000000000d1",
      resume_id: null,
      config: { interview_type: "case", difficulty: "tough", mode: "coach", duration_min: 30, level: "mid" },
      channel: "voice",
      brief_ready: true,
      status: "failed",
      started_at: "2026-10-07T09:00:00Z",
      ended_at: "2026-10-07T09:30:00Z",
      minutes_billed: 30,
      failure_reason: null,
    });
    expectApiShape("AdminSessionList", await adminApi.sessions({ status: "failed" }));
    expectApiShape("AdminSessionDetail", await adminApi.session("00000000-0000-4000-8000-0000000000c2"));
  });
});
