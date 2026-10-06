/**
 * Endpoints the web app needs that the API does not have yet. MSW mocks them (src/mocks) so every
 * screen works today. Each block names the workstream that will build the real endpoint; that
 * workstream may change the shape, then updates this file and its mock.
 *
 * The payloads inside the envelopes (SessionConfig) are the shared contracts from packages/core.
 * Job targets, resumes, their lists and the gap analysis are real endpoints now (inputs.ts,
 * gap.ts), and so are the debrief and progress (scoring.ts).
 */
import { request } from "./client";
import type { SessionConfig, SessionStatus } from "./types";

// ---------------------------------------------------------------- P7/P10: sessions

export interface SessionRecord {
  id: string;
  job_target_id: string;
  config: SessionConfig;
  status: SessionStatus;
  started_at: string | null;
  ended_at: string | null;
  minutes_billed: number;
}

export interface CreateSessionRequest {
  job_target_id: string;
  config: SessionConfig;
}

export const sessionsApi = {
  /** HTTP 402 with detail.code "upgrade_required" when the plan does not allow a session. */
  create: (body: CreateSessionRequest) => request<SessionRecord>("POST", "/sessions", body),
  get: (sessionId: string) => request<SessionRecord>("GET", `/sessions/${sessionId}`),
  end: (sessionId: string) => request<SessionRecord>("POST", `/sessions/${sessionId}/end`),
  listForJob: (jobId: string) => request<SessionRecord[]>("GET", `/job-targets/${jobId}/sessions`),
};

// ---------------------------------------------------------------- P9: billing and account

export interface Usage {
  plan: "free" | "paid";
  minutes_used: number;
  /** 0 on the free plan. */
  minutes_cap: number;
  period_end: string | null;
  /** BL-2: the one free interview. */
  free_interview_available: boolean;
}

export interface PlanOffer {
  name: string;
  price_usd_month: number;
  minutes_cap: number;
}

export type ExportStatus = "preparing" | "ready";

export interface ExportJob {
  id: string;
  status: ExportStatus;
  download_url: string | null;
}

export const billingApi = {
  usage: () => request<Usage>("GET", "/billing/usage"),
  plan: () => request<PlanOffer>("GET", "/billing/plan"),
  /** Returns the Stripe Checkout URL to send the browser to. */
  checkout: () => request<{ url: string }>("POST", "/billing/checkout"),
};

export const accountApi = {
  /** AC-2. */
  setConsent: (trainingConsent: boolean) =>
    request<{ training_consent: boolean }>("PUT", "/account/consent", {
      training_consent: trainingConsent,
    }),
  /** AC-1. */
  startExport: () => request<ExportJob>("POST", "/account/export"),
  getExport: (exportId: string) => request<ExportJob>("GET", `/account/export/${exportId}`),
  deleteAccount: () => request<void>("DELETE", "/account"),
};
