/**
 * Types for everything the web app shows. Shared contracts come from packages/core through
 * openapi.json (see scripts/export_openapi.py), so they cannot drift from the backend.
 */
import type { components } from "./schema.gen";

type S = components["schemas"];

/**
 * Pydantic writes every field in API responses, defaults included, but the JSON Schema marks
 * fields with defaults as optional. This makes them required again for the response types.
 */
type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

// Sign-in (real endpoints in apps/api auth).
export type AuthState = S["AuthState"];
export type AuthUser = S["AuthUser"];
export type AuthProviders = S["AuthProviders"];
export type MagicLinkSent = S["MagicLinkSent"];

// Job and resume inputs (real endpoints in apps/api inputs, P2).
export type JobTargetCreate = S["JobTargetCreate"];
export type JobTargetUpdate = S["JobTargetUpdate"];
export type JobContext = DeepRequired<S["JobContext"]>;
export type JobTargetOut = DeepRequired<S["JobTargetOut"]>;
export type JobTargetAccepted = DeepRequired<S["JobTargetAccepted"]>;
export type ResumeOut = DeepRequired<S["ResumeOut"]>;
export type ResumeAccepted = DeepRequired<S["ResumeAccepted"]>;
/** A background job (Arq) that extracts a posting or parses a resume. */
export type JobOut = DeepRequired<S["JobOut"]>;
/** One row of the dashboard list (GET /job-targets). */
export type JobTargetSummary = DeepRequired<S["JobTargetSummary"]>;

// Gap analysis (real endpoints in apps/api gap, P6).
export type GapAnalysisStart = S["GapAnalysisStart"];
export type GapAnalysisOut = DeepRequired<S["GapAnalysisOut"]>;
export type GapStatus = S["GapStatus"];

// Debrief and progress (real endpoints in apps/api scoring, P8).
export type Debrief = DeepRequired<S["Debrief"]>;
export type DebriefStatus = Debrief["status"];
export type DebriefSession = DeepRequired<S["DebriefSession"]>;
export type JobProgress = DeepRequired<S["JobProgress"]>;
export type CompetencyTrend = DeepRequired<S["CompetencyTrend"]>;

// Billing and account (real endpoints in apps/api billing and account, P9).
export type Usage = DeepRequired<S["UsageOut"]>;
export type ModelUsage = S["ModelUsage"];
export type PlanOffer = S["PlanOut"];
export type ExportJob = DeepRequired<S["ExportOut"]>;
export type ExportStatus = S["ExportOut"]["status"];
export type ExitSurveyIn = S["ExitSurveyIn"];
export type ExitReason = S["ExitSurveyIn"]["reason"];
export type GotJob = S["ExitSurveyIn"]["got_job"];

// Shared contracts from strong_core.schemas.
export type JobPosting = DeepRequired<S["JobPosting"]>;
export type Resume = DeepRequired<S["Resume"]>;
export type GapAnalysis = DeepRequired<S["GapAnalysis"]>;
export type PlannedSession = DeepRequired<S["PlannedSession"]>;
export type SessionConfig = DeepRequired<S["SessionConfig"]>;
export type Scorecard = DeepRequired<S["Scorecard"]>;
export type CompetencyScore = DeepRequired<S["CompetencyScore"]>;
export type QuestionScore = DeepRequired<S["QuestionScore"]>;
export type ValueScore = DeepRequired<S["ValueScore"]>;
export type ProgressSnapshot = DeepRequired<S["ProgressSnapshot"]>;
export type Turn = DeepRequired<S["Turn"]>;
export type Phase = S["Phase"];
export type Level = S["Level"];
export type RoleFamily = S["RoleFamily"];
export type InterviewType = S["InterviewType"];
export type Difficulty = S["Difficulty"];
export type Mode = S["Mode"];
export type HireSignal = S["HireSignal"];
export type Competency = S["Competency"];
export type Severity = S["Severity"];
export type SessionStatus = S["SessionStatus"];
export type SubscriptionStatus = S["SubscriptionStatus"];
