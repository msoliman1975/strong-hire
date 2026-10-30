/**
 * Target roles, interviews and readiness per interview (U06: TG-3, RH-1, RH-2). Real API endpoints.
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type {
  InterviewDetail,
  InterviewOut,
  InterviewsCreate,
  InterviewWithReadiness,
  Rehearsals,
  RoleOut,
  SuggestedInterviews,
} from "./types";

export const rolesApi = {
  /** TG-1: every live role with one readiness per interview, newest first. */
  list: async () => unwrap(await apiClient.GET("/roles")) as RoleOut[],
  /** TG-3: the company's usual rounds for the role. */
  suggested: async (jobId: string) =>
    unwrap(
      await apiClient.GET("/roles/{job_target_id}/suggested-interviews", {
        params: { path: { job_target_id: jobId } },
      }),
    ) as SuggestedInterviews,
  interviews: async (jobId: string) =>
    unwrap(
      await apiClient.GET("/roles/{job_target_id}/interviews", { params: { path: { job_target_id: jobId } } }),
    ) as InterviewWithReadiness[],
  /** RH-1: keep these types as the role's interviews. */
  addInterviews: async (jobId: string, body: InterviewsCreate) =>
    unwrap(
      await apiClient.POST("/roles/{job_target_id}/interviews", {
        params: { path: { job_target_id: jobId } },
        body,
      }),
    ) as InterviewOut[],
  archiveInterview: async (interviewId: string) => {
    unwrap(
      await apiClient.DELETE("/interviews/{interview_id}", {
        params: { path: { interview_id: interviewId } },
        parseAs: "text",
      }),
    );
  },
  /** RH-2, RH-3: the interview, its role, readiness and takes. */
  interview: async (interviewId: string) =>
    unwrap(
      await apiClient.GET("/interviews/{interview_id}", { params: { path: { interview_id: interviewId } } }),
    ) as InterviewDetail,
  /** RH-4: every interview and the recommended next take. */
  rehearsals: async () => unwrap(await apiClient.GET("/rehearsals")) as Rehearsals,
};

export const roleKeys = {
  roles: ["roles"] as const,
  role: (jobId: string) => ["roles", jobId] as const,
  suggested: (jobId: string) => ["roles", jobId, "suggested"] as const,
  interview: (id: string) => ["interviews", id] as const,
  rehearsals: ["rehearsals"] as const,
};

export const useRoles = () => useQuery({ queryKey: roleKeys.roles, queryFn: rolesApi.list });
export const useRoleInterviews = (jobId: string) =>
  useQuery({ queryKey: roleKeys.role(jobId), queryFn: () => rolesApi.interviews(jobId), enabled: Boolean(jobId) });
export const useSuggestedInterviews = (jobId: string | null, enabled = true) =>
  useQuery({
    queryKey: roleKeys.suggested(jobId ?? ""),
    queryFn: () => rolesApi.suggested(jobId ?? ""),
    enabled: Boolean(jobId) && enabled,
  });
export const useInterview = (id: string) =>
  useQuery({ queryKey: roleKeys.interview(id), queryFn: () => rolesApi.interview(id), enabled: Boolean(id) });
export const useRehearsals = () => useQuery({ queryKey: roleKeys.rehearsals, queryFn: rolesApi.rehearsals });
