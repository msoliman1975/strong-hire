/** v2 Part 1 (S16): the tone and difficulty mix (AD-3) and the auto-profile queue (AP-3). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";
import { ADMIN_WRITE } from "./settings";

export type Part1Usage = components["schemas"]["Part1Usage"];
export type MixWeek = components["schemas"]["MixWeek"];
export type AdminAutoProfile = components["schemas"]["AdminAutoProfile"];
export type AdminAutoProfiles = components["schemas"]["AdminAutoProfiles"];
export type AutoProfileStatus = AdminAutoProfile["status"];
export type AutoProfileFilter = AutoProfileStatus | "all";

export const TONES = ["as_company", "warm", "neutral", "direct"] as const;
export const DIFFICULTIES = ["friendly", "realistic", "tough"] as const;
export const TONE_LABEL: Record<(typeof TONES)[number], string> = {
  as_company: "As the company",
  warm: "Warm",
  neutral: "Neutral",
  direct: "Direct",
};
export const DIFFICULTY_LABEL: Record<(typeof DIFFICULTIES)[number], string> = {
  friendly: "Friendly",
  realistic: "Realistic",
  tough: "Tough",
};

export const part1Api = {
  usage: async (weeks: number) =>
    unwrap(await apiClient.GET("/admin/part1/usage", { params: { query: { weeks } } })),
  autoProfiles: async (status: AutoProfileFilter) =>
    unwrap(await apiClient.GET("/admin/auto-profiles", { params: { query: { status } } })),
  approve: async ({ id, reason }: { id: string; reason: string }) =>
    unwrap(
      await apiClient.POST("/admin/auto-profiles/{profile_id}/approve", {
        params: { path: { profile_id: id } },
        body: { reason },
        headers: ADMIN_WRITE,
      }),
    ),
  editSummary: async ({ id, reason, summary }: { id: string; reason: string; summary: string }) =>
    unwrap(
      await apiClient.PUT("/admin/auto-profiles/{profile_id}/summary", {
        params: { path: { profile_id: id } },
        body: { reason, summary },
        headers: ADMIN_WRITE,
      }),
    ),
  retire: async ({ id, reason }: { id: string; reason: string }) =>
    unwrap(
      await apiClient.POST("/admin/auto-profiles/{profile_id}/retire", {
        params: { path: { profile_id: id } },
        body: { reason },
        headers: ADMIN_WRITE,
      }),
    ),
};

export const part1Keys = {
  usage: (weeks: number) => ["admin", "part1", "usage", weeks] as const,
  autoProfiles: ["admin", "auto-profiles"] as const,
};

export const usePart1Usage = (weeks: number) =>
  useQuery({ queryKey: part1Keys.usage(weeks), queryFn: () => part1Api.usage(weeks) });

export const useAutoProfiles = (status: AutoProfileFilter) =>
  useQuery({ queryKey: [...part1Keys.autoProfiles, status], queryFn: () => part1Api.autoProfiles(status) });

/** One of the three AP-3 actions; each refreshes the queue and its counts. */
export function useAutoProfileAction<T>(fn: (body: T) => Promise<AdminAutoProfile>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: part1Keys.autoProfiles }),
  });
}
