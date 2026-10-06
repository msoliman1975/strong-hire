/**
 * Endpoints the web app needs that the API does not have yet. MSW mocks them (src/mocks) so every
 * screen works today. Each block names the workstream that will build the real endpoint; that
 * workstream may change the shape, then updates this file and its mock.
 *
 * The payloads inside the envelopes (GapAnalysis, SessionConfig, Scorecard, ProgressSnapshot,
 * PlannedSession) are the shared contracts from packages/core. Job targets and resumes use the
 * real API types (JobTargetOut, ResumeOut) from openapi.json.
 */
import { request } from "./client";
import type {
  GapAnalysis,
  JobTargetOut,
  PlannedSession,
  ProgressSnapshot,
  ResumeOut,
  Scorecard,
  SessionConfig,
  SessionStatus,
} from "./types";

// ---------------------------------------------------------------- job and resume lists
// P2 built the job target and resume endpoints (see inputs.ts). These two lists are not in the
// API yet. No workstream owns them yet; the dashboard (P8) and resume reuse need them.

export interface JobTargetSummary {
  job_target: JobTargetOut;
  /** From the latest gap analysis. Null until one is ready. */
  match_score: number | null;
  sessions_count: number;
  last_session_at: string | null;
}

export const jobListApi = {
  list: () => request<JobTargetSummary[]>("GET", "/job-targets"),
};

export const resumeListApi = {
  list: () => request<ResumeOut[]>("GET", "/resumes"),
};

// ---------------------------------------------------------------- P6: gap analysis

export type GapStatus = "running" | "ready" | "failed";

export interface GapAnalysisResult {
  job_target_id: string;
  resume_id: string;
  status: GapStatus;
  analysis: GapAnalysis | null;
  error: string | null;
}

export interface StartGapAnalysisRequest {
  /** The resume to compare with the job. A job target has no resume of its own. */
  resume_id: string;
}

export const gapApi = {
  /** Starts or restarts the analysis. Free and rate limited (GA-4). */
  start: (jobId: string, body: StartGapAnalysisRequest) =>
    request<GapAnalysisResult>("POST", `/job-targets/${jobId}/gap-analysis`, body),
  get: (jobId: string) => request<GapAnalysisResult>("GET", `/job-targets/${jobId}/gap-analysis`),
};

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

// ---------------------------------------------------------------- P8: debrief and progress

export type DebriefStatus = "scoring" | "ready" | "failed";

export interface Debrief {
  session: SessionRecord;
  status: DebriefStatus;
  scorecard: Scorecard | null;
  /** PR-2. */
  next_session: PlannedSession | null;
}

export interface JobProgress {
  job_target_id: string;
  /** Realistic sessions only (PR-1). */
  snapshots: ProgressSnapshot[];
  next_session: PlannedSession | null;
}

export const debriefApi = {
  get: (sessionId: string) => request<Debrief>("GET", `/sessions/${sessionId}/debrief`),
  progress: (jobId: string) => request<JobProgress>("GET", `/job-targets/${jobId}/progress`),
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
