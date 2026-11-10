/**
 * The story library's endpoints (ST-1, used by ST-3 and ST-4): GET/POST /stories,
 * GET/PATCH /stories/{id}. The status is never set here; the API sets Proven (ST-7).
 * CS-13 to CS-15: archive, unarchive, delete (soft) and restore. CS-5: the Recommended rows of
 * Career Stories (GET /stories/recommendations).
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "../../api/client";
import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import type { components } from "../../api/schema.gen";
import { outlineReady } from "../coach/outline";

type S = components["schemas"];

/** Pydantic writes every field, defaults included; make them required, as in api/types.ts. */
type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

/** ST-8: every story response carries the status to show (draft, ready or proven). */
export type Story = DeepRequired<S["StoryOut"]>;
export type DisplayStatus = Story["display_status"];
export type StoryAnswer = DeepRequired<S["StoryAnswer"]>;
export type StoryNote = DeepRequired<S["StoryNote"]>;
export type StoryStatus = S["StoryStatus"];
export type StoryIn = S["StoryIn"];
export type StoryPatch = S["StoryPatch"];
export type Competency = S["Competency"];
type Section = S["StorySection"];
export type OutlinePatch = S["OutlinePatch"];
export type SlotEditIn = S["SlotEditIn"];
export type SectionImprove = DeepRequired<S["SectionImprove"]>;
export type SlotEdit = DeepRequired<S["SlotEdit"]>;
export type OrganizeResult = DeepRequired<S["OrganizeResult"]>;
export type StyleSwitchOut = DeepRequired<S["StyleSwitchOut"]>;
export type StoryRecommendations = DeepRequired<S["StoryRecommendations"]>;
export type RecommendedIdea = DeepRequired<S["RecommendedIdea"]>;
export type RecommendedSkill = DeepRequired<S["RecommendedSkill"]>;

export interface StoryFilter {
  status?: StoryStatus;
  skill?: Competency;
  /** CS-6: archived and deleted stories are left out unless asked for. */
  include?: ("archived" | "deleted")[];
}

export const storyKeys = {
  all: ["stories"] as const,
  list: (filter: StoryFilter = {}) =>
    ["stories", "list", filter.status ?? null, filter.skill ?? null, (filter.include ?? []).join(",")] as const,
  one: (id: string) => ["stories", "one", id] as const,
  recommendations: ["stories", "recommendations"] as const,
};

export const storiesApi = {
  list: async (filter: StoryFilter = {}) =>
    unwrap(
      await apiClient.GET("/stories", {
        params: { query: { status: filter.status, skill: filter.skill, include: filter.include } },
      }),
    ) as Story[],
  /** CS-13: archive (out of the list and out of prep, CS-14) and bring back. */
  archive: async (id: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/archive", { params: { path: { story_id: id } } })) as Story,
  unarchive: async (id: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/unarchive", { params: { path: { story_id: id } } })) as Story,
  /** CS-15: delete is soft; restore within 30 days. */
  remove: async (id: string) => {
    unwrap(await apiClient.DELETE("/stories/{story_id}", { params: { path: { story_id: id } } }));
  },
  restore: async (id: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/restore", { params: { path: { story_id: id } } })) as Story,
  /** CS-1 to CS-5, CS-11: resume ideas pooled across resumes, and job skill gaps. */
  recommendations: async () =>
    unwrap(await apiClient.GET("/stories/recommendations")) as StoryRecommendations,
  get: async (id: string) =>
    unwrap(await apiClient.GET("/stories/{story_id}", { params: { path: { story_id: id } } })) as Story,
  create: async (body: StoryIn) => unwrap(await apiClient.POST("/stories", { body })) as Story,
  /** Only the fields sent change; a part sent as null or blank is cleared. */
  update: async (id: string, body: StoryPatch) =>
    unwrap(await apiClient.PATCH("/stories/{story_id}", { params: { path: { story_id: id } }, body })) as Story,
  /** ST-11: queue Strova's review; it arrives as an open `review` suggestion for the story. */
  review: async (id: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/review", { params: { path: { story_id: id } } })) as {
      job_id: string;
    },
  /** SC-10: the user's inline slot edits, skips and step order on a styled story. */
  editOutline: async (id: string, body: OutlinePatch) =>
    unwrap(
      await apiClient.PATCH("/stories/{story_id}/outline", { params: { path: { story_id: id } }, body }),
    ) as Story,
  /** SC-11: Strova's before-and-after edits or questions for one section; writes nothing. */
  improve: async (id: string, section: Section, note: string | null) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/sections/{section}/improve", {
        params: { path: { story_id: id, section } },
        body: { note },
      }),
    ) as SectionImprove,
  /** SC-11: apply the accepted edits (checked again against the user's words). */
  acceptImprove: async (id: string, section: Section, edits: SlotEdit[], note: string | null) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/sections/{section}/improve/accept", {
        params: { path: { story_id: id, section } },
        body: { edits, note },
      }),
    ) as Story,
  /** SC-13: a classic story as a STAR preview; writes nothing. */
  organize: async (id: string) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/organize", { params: { path: { story_id: id } } }),
    ) as OrganizeResult,
  acceptOrganize: async (id: string, body: OrganizeResult) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/organize/accept", {
        params: { path: { story_id: id } },
        body: body as S["OrganizeResult"],
      }),
    ) as Story,
  /** SC-12: switch style; without rewrite it saves at once, with it it returns a preview. */
  switchStyle: async (id: string, style: S["StoryStyle"], rewrite: boolean) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/style", {
        params: { path: { story_id: id } },
        body: { style, rewrite },
      }),
    ) as StyleSwitchOut,
  acceptStyle: async (id: string, outline: NonNullable<Story["outline"]>) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/style/accept", {
        params: { path: { story_id: id } },
        body: outline as S["StoryOutline"],
      }),
    ) as Story,
  /** ST-13: Strova answers from the user's stories and roles. */
  ask: async (question: string) =>
    unwrap(await apiClient.POST("/stories/ask", { body: { question } })) as StoryAnswer,
};

export const useStories = (filter: StoryFilter = {}) =>
  useQuery({ queryKey: storyKeys.list(filter), queryFn: () => storiesApi.list(filter) });

export const useStory = (id: string) => useQuery({ queryKey: storyKeys.one(id), queryFn: () => storiesApi.get(id) });

export const useStoryRecommendations = () =>
  useQuery({ queryKey: storyKeys.recommendations, queryFn: storiesApi.recommendations });

export const STORY_PARTS = ["context", "stakes", "action", "result", "reflection"] as const;

export const storyStatusLabel: Record<StoryStatus, string> = { draft: "Draft", proven: "Proven" };

/** ST-8: Draft, Ready (all five parts) or Proven. */
export const displayStatusLabel: Record<DisplayStatus, string> = { draft: "Draft", ready: "Ready", proven: "Proven" };

/** ST-8, as the API computes it: Proven stays; all five parts filled is Ready. SC-3: a styled
 * story is Ready when its core slots are filled. */
export function displayStatusOf(
  s: Pick<Story, "status" | (typeof STORY_PARTS)[number]> & { outline?: Story["outline"] },
): DisplayStatus {
  if (s.status === "proven") return "proven";
  if (s.outline) return outlineReady(s.outline) ? "ready" : "draft";
  return STORY_PARTS.every((p) => (s[p] ?? "").trim() !== "") ? "ready" : "draft";
}

/** The parts with text, in order. */
export const filledParts = (s: Story) => STORY_PARTS.filter((p) => (s[p] ?? "").trim() !== "");

/** Every competency once, in the order of COMPETENCIES_BY_TYPE. The recruiter screen repeats three. */
export const SKILLS = [...new Set(Object.values(COMPETENCIES_BY_TYPE).flat())] as Competency[];
