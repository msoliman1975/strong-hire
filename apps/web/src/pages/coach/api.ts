/**
 * The coach, takes and versions endpoints (CO-2 to CO-8), from strong_api.coach and
 * strong_api.takes:
 *   POST /coach/sessions, GET /coach/sessions/{id}, POST .../turns, .../style, .../end
 *   GET/POST /stories/{id}/takes, GET /stories/{id}/takes/{take_id}, POST /stories/{id}/versions
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";
import type { Story } from "../stories/api";

type S = components["schemas"];

export type CoachStyle = S["CoachStyle"];
export type AskFor = S["AskFor"];
export type StoryPart = S["StoryPart"];
export type StartCoachRequest = S["StartCoachRequest"];
export type CoachSessionOut = S["CoachSessionOut"];
export type CoachTurnOut = S["CoachTurnOut"];
export type CoachReply = S["CoachReply"];
export type CoachSessionDetail = Omit<S["CoachSessionDetail"], "story"> & { story: Story | null };
export type CoachTurnResult = Omit<S["CoachTurnResult"], "story"> & { story: Story | null };
export type TakeOut = S["TakeOut"];
export type TakeRequest = S["TakeRequest"];
export type StoryVersions = S["StoryVersions"];

export const coachKeys = {
  session: (id: string) => ["coach", "session", id] as const,
  takes: (storyId: string) => ["stories", "takes", storyId] as const,
};

export const coachApi = {
  start: async (body: StartCoachRequest) =>
    unwrap(await apiClient.POST("/coach/sessions", { body })) as CoachSessionDetail,
  get: async (id: string) =>
    unwrap(
      await apiClient.GET("/coach/sessions/{session_id}", { params: { path: { session_id: id } } }),
    ) as CoachSessionDetail,
  turn: async (id: string, text: string) =>
    unwrap(
      await apiClient.POST("/coach/sessions/{session_id}/turns", {
        params: { path: { session_id: id } },
        body: { text },
      }),
    ) as CoachTurnResult,
  /** CO-5: the next reply uses the new style. */
  style: async (id: string, style: CoachStyle) =>
    unwrap(
      await apiClient.POST("/coach/sessions/{session_id}/style", {
        params: { path: { session_id: id } },
        body: { style },
      }),
    ),
  end: async (id: string) =>
    unwrap(
      await apiClient.POST("/coach/sessions/{session_id}/end", { params: { path: { session_id: id } } }),
    ) as CoachSessionDetail,
};

export const takesApi = {
  list: async (storyId: string) =>
    unwrap(await apiClient.GET("/stories/{story_id}/takes", { params: { path: { story_id: storyId } } })),
  /** CO-7: stores the take and queues its scoring on the story's skills. */
  create: async (storyId: string, body: TakeRequest) =>
    unwrap(await apiClient.POST("/stories/{story_id}/takes", { params: { path: { story_id: storyId } }, body })),
  /** CO-8: written on request from the candidate's own words; not stored. */
  versions: async (storyId: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/versions", { params: { path: { story_id: storyId } } })),
};

export const useCoachSession = (id: string) =>
  useQuery({ queryKey: coachKeys.session(id), queryFn: () => coachApi.get(id) });

const POLL_MS = 2000;

/** The story's takes, newest first. Polls while a take is being scored. */
export const useTakes = (storyId: string) =>
  useQuery({
    queryKey: coachKeys.takes(storyId),
    queryFn: () => takesApi.list(storyId),
    refetchInterval: (query) => (query.state.data?.some((t) => t.status === "scoring") ? POLL_MS : false),
  });

/** CO-4: the story part each "asking for" fills. */
export const ASK_PART: Record<AskFor, StoryPart | null> = {
  concrete_example: "context",
  stakes: "stakes",
  own_role: "action",
  measurable_result: "result",
  tradeoff_reasoning: "action",
  reflection: "reflection",
  nothing: null,
};

/** Shown wherever take scores show. */
export const PRACTICE_NOTICE =
  "Take scores are practice estimates from an AI coach. They are not a prediction of any hiring decision.";
