/**
 * Gap analysis (P6, GA-1 to GA-4). These endpoints exist in the API, so they use the typed client.
 *
 * `start` returns 202 with the new run (status "running"). Poll `get` until the status is
 * "ready" or "failed". Gap analysis is free; the API rate limits it per user and answers 429
 * with code "rate_limited" when the user starts too many.
 */
import { ApiError, apiClient, unwrap } from "./client";
import type { GapAnalysisOut, GapAnalysisStart } from "./types";

export const gapApi = {
  /**
   * Start or restart. Leave `resume_id` out to run again with the resume of the last run.
   * With `reuse_ready` (R1), a ready analysis of the same saved job and CV comes back instead.
   */
  start: async (jobTargetId: string, body: Partial<GapAnalysisStart> = {}) =>
    unwrap(
      await apiClient.POST("/job-targets/{job_target_id}/gap-analysis", {
        params: { path: { job_target_id: jobTargetId } },
        body: { reuse_ready: false, ...body },
      }),
    ) as GapAnalysisOut,
  /** One run by id, for the Reports page (R1). Works for a deleted job too. */
  getById: async (gapAnalysisId: string) =>
    unwrap(
      await apiClient.GET("/gap-analyses/{gap_analysis_id}", {
        params: { path: { gap_analysis_id: gapAnalysisId } },
      }),
    ) as GapAnalysisOut,
  /** The latest run. HTTP 404 when none was started. */
  get: async (jobTargetId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}/gap-analysis", {
        params: { path: { job_target_id: jobTargetId } },
      }),
    ) as GapAnalysisOut,
  /**
   * Waits until a ready analysis of this job and resume exists: the latest run when it matches,
   * else a new one (a ready one is reused). The interview page uses it before the first take,
   * because the analysis a new role starts runs in the background. Throws when it fails.
   */
  whenReady: async (jobTargetId: string, resumeId: string, intervalMs = 1500, timeoutMs = 120_000) => {
    let run: GapAnalysisOut | null = null;
    try {
      run = await gapApi.get(jobTargetId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    if (!run || run.resume_id !== resumeId || run.status === "failed")
      run = await gapApi.start(jobTargetId, { resume_id: resumeId, reuse_ready: true });
    const until = Date.now() + timeoutMs;
    while (run.status !== "ready") {
      if (run.status === "failed") throw new Error("Strova could not prepare this interview. Try again.");
      if (Date.now() > until) throw new Error("Preparing this interview is taking longer than usual. Try again in a minute.");
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      run = await gapApi.getById(run.id);
    }
    return run;
  },
};
