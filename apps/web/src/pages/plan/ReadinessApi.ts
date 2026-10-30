/**
 * Practice readiness (RD-1, RD-3): GET /readiness/{job}. The day plan types (RD-2) stay for the
 * mocks; U13 removed the retired v2 plan page that read the pair readiness and the day plan.
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";

type S = components["schemas"];

type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

export type Readiness = DeepRequired<S["Readiness"]>;
export type DayPlan = DeepRequired<S["DayPlan"]>;
export type DayPlanItem = DeepRequired<S["DayPlanItem"]>;

/** RD-3: shown on every screen that shows readiness. */
export const READINESS_NOTICE =
  "Practice readiness is an estimate from your scored Realistic rehearsals. It is not a prediction of the hiring decision.";
export const READINESS_NOTICE_SHORT = "Practice estimate, not a prediction.";

/** A 3 of 4 on the rubric, as the API's 0 to 100 score (strong_api.plan.readiness.BAR_SCORE). */
export const BAR_SCORE = 67;
/** strong_api.plan.readiness.MIN_SESSIONS. */
export const MIN_SESSIONS = 2;

export const atBar = (r: Readiness) => r.skills.filter((s) => s.score !== null && s.score >= BAR_SCORE).length;
export const scored = (r: Readiness) => r.skills.filter((s) => s.status === "scored").length;

export const jobReadinessKey = (jobId: string) => ["readiness", jobId] as const;

const readinessApi = {
  job: async (jobId: string) =>
    unwrap(
      await apiClient.GET("/readiness/{job_target_id}", { params: { path: { job_target_id: jobId } } }),
    ) as Readiness,
};

export const useJobReadiness = (jobId: string) =>
  useQuery({ queryKey: jobReadinessKey(jobId), queryFn: () => readinessApi.job(jobId) });
