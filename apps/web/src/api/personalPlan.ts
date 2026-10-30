/** The personal plan (U11: PS-1 to PS-5, HO-1): GET /me/plan in the user's style. */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { PersonalPlan } from "./types";

export const personalPlanKey = ["me", "plan"] as const;

export const personalPlanApi = {
  get: async () => unwrap(await apiClient.GET("/me/plan")) as PersonalPlan,
};

export const usePersonalPlan = () => useQuery({ queryKey: personalPlanKey, queryFn: personalPlanApi.get });
