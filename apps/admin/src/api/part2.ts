/** v2 Part 2 (S25): story library metrics (AD-4). Aggregate only: no story text reaches admin. */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

export type Part2Stories = components["schemas"]["Part2Stories"];
export type DeliveryWeek = components["schemas"]["DeliveryWeek"];

export const STORY_SOURCES = ["debrief_answer", "manual", "coach"] as const;
export const STORY_SOURCE_LABEL: Record<(typeof STORY_SOURCES)[number], string> = {
  debrief_answer: "Saved from a debrief",
  manual: "Written by hand",
  coach: "From the coach",
};

export const part2Api = {
  stories: async (weeks: number) =>
    unwrap(await apiClient.GET("/admin/part2/stories", { params: { query: { weeks } } })),
};

export const part2Keys = {
  stories: (weeks: number) => ["admin", "part2", "stories", weeks] as const,
};

export const usePart2Stories = (weeks: number) =>
  useQuery({ queryKey: part2Keys.stories(weeks), queryFn: () => part2Api.stories(weeks) });
