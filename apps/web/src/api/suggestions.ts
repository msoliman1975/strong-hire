/**
 * Suggestions from Strova (U08: SG-2 to SG-8). Real API endpoints in strong_api.suggestions:
 * list by place, accept (optionally with an edited text), dismiss and undo.
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { Suggestion, SuggestionAcceptIn, SuggestionAcceptOut } from "./types";

export type SuggestionPlace = "debrief" | "story" | "role" | "stories" | "resume";

export const suggestionsApi = {
  list: async (
    place: SuggestionPlace,
    ids: { session_id?: string; story_id?: string; job_target_id?: string; resume_id?: string } = {},
  ) => unwrap(await apiClient.GET("/suggestions", { params: { query: { place, ...ids } } })) as Suggestion[],
  accept: async (id: string, body: SuggestionAcceptIn = {}) =>
    unwrap(
      await apiClient.POST("/suggestions/{suggestion_id}/accept", {
        params: { path: { suggestion_id: id } },
        body,
      }),
    ) as SuggestionAcceptOut,
  dismiss: async (id: string) =>
    unwrap(
      await apiClient.POST("/suggestions/{suggestion_id}/dismiss", { params: { path: { suggestion_id: id } } }),
    ) as Suggestion,
  undo: async (id: string) =>
    unwrap(
      await apiClient.POST("/suggestions/{suggestion_id}/undo", { params: { path: { suggestion_id: id } } }),
    ) as Suggestion,
};

export const suggestionKeys = {
  place: (place: SuggestionPlace, id = "") => ["suggestions", place, id] as const,
};

export const useSuggestions = (place: SuggestionPlace, ids: Parameters<typeof suggestionsApi.list>[1] = {}) =>
  useQuery({
    queryKey: suggestionKeys.place(place, Object.values(ids).join(",")),
    queryFn: () => suggestionsApi.list(place, ids),
  });
