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
