/**
 * Interview sessions (P7) and the voice room (P10). These endpoints exist in the API, so they use
 * the typed client.
 *
 * A new session has status "created" and brief_ready false until the worker builds the
 * interviewer brief. The first voice join starts the session ("in_progress"). The voice agent
 * ends it; the API then bills the minutes and scores it ("scoring", then "completed").
 */
import { apiClient, unwrap } from "./client";
import type { CreateSessionRequest, SessionRecord, VoiceJoin } from "./types";

export type { CreateSessionRequest, SessionRecord, VoiceJoin };

export const sessionsApi = {
  /** HTTP 402 with detail.code "upgrade_required" when the plan does not allow a session. */
  create: async (body: CreateSessionRequest) => unwrap(await apiClient.POST("/sessions", { body })) as SessionRecord,
  get: async (sessionId: string) =>
    unwrap(
      await apiClient.GET("/sessions/{session_id}", {
        params: { path: { session_id: sessionId } },
      }),
    ) as SessionRecord,
  end: async (sessionId: string) =>
    unwrap(
      await apiClient.POST("/sessions/{session_id}/end", {
        params: { path: { session_id: sessionId } },
      }),
    ) as SessionRecord,
  listForJob: async (jobId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}/sessions", {
        params: { path: { job_target_id: jobId } },
      }),
    ) as SessionRecord[],
  /** Starts the session on the first call. Call again after a dropped connection (IV-9). */
  joinVoice: async (sessionId: string) =>
    unwrap(
      await apiClient.POST("/sessions/{session_id}/voice/join", {
        params: { path: { session_id: sessionId } },
      }),
    ) as VoiceJoin,
};
