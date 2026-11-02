/**
 * Resume comparison (RC-1 to RC-8): which of the user's resumes fits a role best, and its gaps.
 *
 * `start` returns 202 with the comparison; poll `get` while its status is "running". Comparing
 * runs only when the user asks (RC-1). A comparison that needs any new analysis counts as one
 * gap analysis run (RC-7), so it can answer 429 with code "rate_limited".
 */
import { useQuery } from "@tanstack/react-query";

import { ApiError, apiClient, unwrap } from "./client";
import type { ResumeComparisonOut } from "./types";

export const compareApi = {
  start: async (jobId: string) =>
    unwrap(
      await apiClient.POST("/roles/{job_target_id}/resume-comparison", {
        params: { path: { job_target_id: jobId } },
      }),
    ) as ResumeComparisonOut,
  /** The role's latest comparison, or null when none was started. */
  get: async (jobId: string): Promise<ResumeComparisonOut | null> => {
    try {
      return unwrap(
        await apiClient.GET("/roles/{job_target_id}/resume-comparison", {
          params: { path: { job_target_id: jobId } },
        }),
      ) as ResumeComparisonOut;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },
  /** RC-6: the role uses this resume from now on. */
  use: async (comparisonId: string, resumeId: string) =>
    unwrap(
      await apiClient.POST("/resume-comparisons/{comparison_id}/use", {
        params: { path: { comparison_id: comparisonId } },
        body: { resume_id: resumeId },
      }),
    ) as ResumeComparisonOut,
  /** RC-4: copy the covering line into the resume, unchanged. */
  addLine: async (comparisonId: string, key: string) =>
    unwrap(
      await apiClient.POST("/resume-comparisons/{comparison_id}/hints/{key}/add", {
        params: { path: { comparison_id: comparisonId, key } },
      }),
    ) as ResumeComparisonOut,
  /** RC-4: hide the hint. */
  dismiss: async (comparisonId: string, key: string) =>
    unwrap(
      await apiClient.POST("/resume-comparisons/{comparison_id}/hints/{key}/dismiss", {
        params: { path: { comparison_id: comparisonId, key } },
      }),
    ) as ResumeComparisonOut,
};

export const compareKeys = {
  comparison: (jobId: string) => ["resume-comparison", jobId] as const,
};

const POLL_MS = 1500;

/** The role's latest comparison; polls while its analyses run. */
export const useResumeComparison = (jobId: string, enabled = true) =>
  useQuery({
    queryKey: compareKeys.comparison(jobId),
    queryFn: () => compareApi.get(jobId),
    enabled: Boolean(jobId) && enabled,
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });
