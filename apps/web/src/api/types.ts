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

// Shared contracts from strong_core.schemas.
export type JobPosting = DeepRequired<S["JobPosting"]>;
export type Resume = DeepRequired<S["Resume"]>;
export type GapAnalysis = DeepRequired<S["GapAnalysis"]>;
export type PlannedSession = DeepRequired<S["PlannedSession"]>;
export type SessionConfig = DeepRequired<S["SessionConfig"]>;
export type Scorecard = DeepRequired<S["Scorecard"]>;
export type CompetencyScore = DeepRequired<S["CompetencyScore"]>;
export type QuestionScore = DeepRequired<S["QuestionScore"]>;
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
