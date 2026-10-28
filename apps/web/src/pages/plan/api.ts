/** The interview plan page's endpoints (PP-1, PP-2): GET /plan/{job}/{resume}, PUT .../interview-date. */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";

type S = components["schemas"];

/** Pydantic writes every field, defaults included; make them required, as in api/types.ts. */
type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

export type PlanView = DeepRequired<S["PlanView"]>;
export type TypeWeights = DeepRequired<S["TypeWeights"]>;
export type PlanSetupDefaults = DeepRequired<S["PlanSetupDefaults"]>;
export type InterviewDateOut = DeepRequired<S["InterviewDateOut"]>;
export type Tone = S["Tone"];

export const planKey = (jobId: string, resumeId: string) => ["plan", jobId, resumeId] as const;

export const planApi = {
  get: async (jobId: string, resumeId: string) =>
    unwrap(
      await apiClient.GET("/plan/{job_target_id}/{resume_id}", {
        params: { path: { job_target_id: jobId, resume_id: resumeId } },
      }),
    ) as PlanView,
  /** PP-2: a date in the past answers 422. `null` clears it. */
  setInterviewDate: async (jobId: string, interviewDate: string | null) =>
    unwrap(
      await apiClient.PUT("/plan/{job_target_id}/interview-date", {
        params: { path: { job_target_id: jobId } },
        body: { interview_date: interviewDate },
      }),
    ) as InterviewDateOut,
};

/** PP-1. Polls while the pair's gap analysis is still running. */
export const usePlan = (jobId: string, resumeId: string) =>
  useQuery({
    queryKey: planKey(jobId, resumeId),
    queryFn: () => planApi.get(jobId, resumeId),
    refetchInterval: (query) => (query.state.data?.gap?.status === "running" ? 1000 : false),
  });
