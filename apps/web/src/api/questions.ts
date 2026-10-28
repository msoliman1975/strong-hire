/**
 * The Questions page (QB-1 to QB-3): the question bank with filters. The API does the
 * filtering; the page keeps the filters in the URL so the debrief can link to a filtered view.
 */
import { apiClient, unwrap } from "./client";
import type { BankCompany, Competency, Level, QuestionList, RoleFamily, StandardType } from "./types";

/** A type the bank can filter by: the four standard types, and Recruiter screen (RS-1). */
export type BankType = StandardType | "recruiter_screen";

/** `company` is a company slug, "general" for general questions only, or null for all. */
export interface QuestionFilter {
  company?: string | null;
  interviewType?: BankType | null;
  competencies?: Competency[];
  roleFamily?: RoleFamily | null;
  level?: Level | null;
  text?: string | null;
}

export const GENERAL = "general";

export const questionsApi = {
  companies: async () => unwrap(await apiClient.GET("/questions/companies")) as BankCompany[],
  list: async (filter: QuestionFilter = {}) =>
    unwrap(
      await apiClient.GET("/questions", {
        params: {
          query: {
            company: filter.company ?? undefined,
            interview_type: filter.interviewType ?? undefined,
            competency: filter.competencies?.length ? filter.competencies : undefined,
            role_family: filter.roleFamily ?? undefined,
            level: filter.level ?? undefined,
            q: filter.text?.trim() || undefined,
          },
        },
      }),
    ) as QuestionList,
};

/**
 * Mirrors COMPETENCIES_BY_TYPE in strong_core.schemas.enums. Display only: it narrows the area
 * filter to the chosen interview type. A test checks it covers every Competency.
 */
export const COMPETENCIES_BY_TYPE: Record<BankType, Competency[]> = {
  behavioral: ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"],
  hiring_manager: ["role_fit", "depth_of_experience", "judgment", "motivation", "team_fit", "scope_at_level"],
  technical_qa: ["technical_depth", "accuracy", "reasoning", "trade_offs", "clarity_of_explanation"],
  case: [
    "problem_framing",
    "structure",
    "user_and_business_sense",
    "estimation_logic",
    "prioritization",
    "recommendation",
  ],
  // RS-1: shares motivation, role fit and communication with the types above.
  recruiter_screen: ["motivation", "role_fit", "communication", "logistics_and_expectations"],
};
