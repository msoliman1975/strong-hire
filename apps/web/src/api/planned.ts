/**
 * Endpoints the web app needs that the API does not have yet. MSW mocks them (src/mocks) so every
 * screen works today. Each block names the workstream that will build the real endpoint; that
 * workstream may change the shape, then updates this file and its mock.
 *
 * The payloads inside the envelopes (JobPosting, Resume, GapAnalysis, SessionConfig, Scorecard,
 * ProgressSnapshot, PlannedSession) are the shared contracts from packages/core.
 */
import { request } from "./client";
import type {
  GapAnalysis,
  JobPosting,
  Level,
  PlannedSession,
  ProgressSnapshot,
  Resume,
  Scorecard,
  SessionConfig,
  SessionStatus,
} from "./types";

// ---------------------------------------------------------------- P2: job and resume inputs

export type JobStatus = "extracting" | "needs_confirmation" | "confirmed" | "failed";

/** IN-4 optional context. */
export interface JobContext {
  stage: string | null;
  interviewer: string | null;
  recruiter_notes: string | null;
  concerns: string | null;
}

export interface CompanyRef {
  id: string;
  name: string;
  slug: string;
}

export interface JobTarget {
  id: string;
  status: JobStatus;
  source_url: string | null;
  /** Set once extraction finishes. The user confirms or edits it (IN-2). */
  posting: JobPosting | null;
  /** Null means generic mode (IN-5). */
  company: CompanyRef | null;
  level: Level | null;
  context: JobContext | null;
  resume_id: string | null;
  /** Why extraction failed, for example a blocked job board. The user can paste text instead. */
  error: string | null;
  created_at: string;
}

export interface JobTargetSummary {
  job: JobTarget;
  match_score: number | null;
  sessions_count: number;
  last_session_at: string | null;
}

export interface CreateJobRequest {
  source_url?: string;
  raw_text?: string;
}

export type ResumeStatus = "parsing" | "ready" | "failed";

export interface ResumeRecord {
  id: string;
  status: ResumeStatus;
  file_name: string | null;
  parsed: Resume | null;
  error: string | null;
  uploaded_at: string;
}

export const jobsApi = {
  list: () => request<JobTargetSummary[]>("GET", "/jobs"),
  create: (body: CreateJobRequest) => request<JobTarget>("POST", "/jobs", body),
  get: (jobId: string) => request<JobTarget>("GET", `/jobs/${jobId}`),
  /** Saves the confirmed or edited posting (IN-2). */
  confirm: (jobId: string, posting: JobPosting) =>
    request<JobTarget>("PUT", `/jobs/${jobId}/posting`, posting),
  setContext: (jobId: string, context: JobContext) =>
    request<JobTarget>("PUT", `/jobs/${jobId}/context`, context),
  setResume: (jobId: string, resumeId: string) =>
    request<JobTarget>("PUT", `/jobs/${jobId}/resume`, { resume_id: resumeId }),
};

export const resumesApi = {
  list: () => request<ResumeRecord[]>("GET", "/resumes"),
  get: (resumeId: string) => request<ResumeRecord>("GET", `/resumes/${resumeId}`),
  /** Multipart: either a `file` (PDF or DOCX) or a `text` field. */
  upload: (form: FormData) => request<ResumeRecord>("POST", "/resumes", form),
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

export const gapApi = {
  /** Starts or restarts the analysis. Free and rate limited (GA-4). */
  start: (jobId: string) => request<GapAnalysisResult>("POST", `/jobs/${jobId}/gap-analysis`),
  get: (jobId: string) => request<GapAnalysisResult>("GET", `/jobs/${jobId}/gap-analysis`),
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
  listForJob: (jobId: string) => request<SessionRecord[]>("GET", `/jobs/${jobId}/sessions`),
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
  progress: (jobId: string) => request<JobProgress>("GET", `/jobs/${jobId}/progress`),
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
