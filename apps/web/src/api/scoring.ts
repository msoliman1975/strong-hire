/**
 * Debrief and progress (P8). These endpoints exist in the API, so they use the typed client.
 *
 * The debrief has status "scoring" until the worker stores the scorecard (FB-3: within 60
 * seconds of the session end), then "ready". "failed" means the session could not be scored.
 */
import { apiClient, unwrap } from "./client";
import type { Debrief, JobProgress } from "./types";

export const debriefApi = {
  /** FB-1, FB-2, PR-2. */
  get: async (sessionId: string) =>
    unwrap(
      await apiClient.GET("/sessions/{session_id}/debrief", {
        params: { path: { session_id: sessionId } },
      }),
    ) as Debrief,
  /** PR-1 (Realistic sessions only) and PR-2. */
  progress: async (jobId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}/progress", {
        params: { path: { job_target_id: jobId } },
      }),
    ) as JobProgress,
};
