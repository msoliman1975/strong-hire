/**
 * v2 Part 3 (S38): the AI coach, readiness by skill and the recruiter screen setup (AD-5).
 * Aggregate only: no coach conversation, take or story text reaches admin.
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];
type Competency = S["Competency"];

export type Part3Coach = S["Part3Coach"];
export type CoachWeek = S["CoachWeek"];
export type CoachEvalRun = S["CoachEvalRun"];
export type Part3Readiness = S["Part3Readiness"];
export type SkillReadinessRow = S["SkillReadinessRow"];
export type AdminSessionSetup = S["AdminSessionSetup"];
export type AdminRubric = S["AdminRubric"];

/** The fields of an InterviewerBrief the setup panel shows. The API sends the whole brief. */
export interface BriefView {
  session?: { interview_type?: string; level?: string };
  target_competencies?: Competency[];
  questions?: { id: string; text: string; competencies?: Competency[]; priority?: number }[];
  probe_areas?: string[];
  persona?: { tone?: string; pushback_style?: string; closing_style?: string };
  seniority_bar?: string | null;
}

export const part3Api = {
  coach: async (weeks: number) =>
    unwrap(await apiClient.GET("/admin/part3/coach", { params: { query: { weeks } } })),
  readiness: async () => unwrap(await apiClient.GET("/admin/part3/readiness")),
};

export const part3Keys = {
  coach: (weeks: number) => ["admin", "part3", "coach", weeks] as const,
  readiness: () => ["admin", "part3", "readiness"] as const,
};

export const usePart3Coach = (weeks: number) =>
  useQuery({ queryKey: part3Keys.coach(weeks), queryFn: () => part3Api.coach(weeks) });

export const usePart3Readiness = () =>
  useQuery({ queryKey: part3Keys.readiness(), queryFn: () => part3Api.readiness() });
