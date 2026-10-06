/**
 * Gap analysis (P6, GA-1 to GA-4). These endpoints exist in the API, so they use the typed client.
 *
 * `start` returns 202 with the new run (status "running"). Poll `get` until the status is
 * "ready" or "failed". Gap analysis is free; the API rate limits it per user and answers 429
 * with code "rate_limited" when the user starts too many.
 */
import { apiClient, unwrap } from "./client";
import type { GapAnalysisOut, GapAnalysisStart } from "./types";

export const gapApi = {
  /** Start or restart. Leave `resume_id` out to run again with the resume of the last run. */
  start: async (jobTargetId: string, body: GapAnalysisStart = {}) =>
    unwrap(
      await apiClient.POST("/job-targets/{job_target_id}/gap-analysis", {
        params: { path: { job_target_id: jobTargetId } },
        body,
      }),
    ) as GapAnalysisOut,
  /** The latest run. HTTP 404 when none was started. */
  get: async (jobTargetId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}/gap-analysis", {
        params: { path: { job_target_id: jobTargetId } },
      }),
    ) as GapAnalysisOut,
};
