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
export type EmailSent = S["EmailSent"];

// Job and resume inputs (real endpoints in apps/api inputs, P2).
export type JobTargetCreate = S["JobTargetCreate"];
export type JobTargetUpdate = S["JobTargetUpdate"];
export type JobContext = DeepRequired<S["JobContext"]>;
export type JobTargetOut = DeepRequired<S["JobTargetOut"]>;
export type JobTargetAccepted = DeepRequired<S["JobTargetAccepted"]>;
export type ResumeOut = DeepRequired<S["ResumeOut"]>;
export type ResumeAccepted = DeepRequired<S["ResumeAccepted"]>;
/** RM-5: the API's rule-based check, open and accepted (GET /resumes/{id}/issues). */
export type ResumeIssues = DeepRequired<S["ResumeIssues"]>;
/** RM-4: story ideas from a resume (GET /resumes/{id}/story-ideas). */
export type StoryIdeasOut = DeepRequired<S["StoryIdeasOut"]>;
export type StoryIdeaOut = DeepRequired<S["StoryIdeaOut"]>;
/** PS-2, PS-6: PATCH /account/profile. */
export type PlanSettingsIn = S["PlanSettingsIn"];
/** A background job (Arq) that extracts a posting or parses a resume. */
export type JobOut = DeepRequired<S["JobOut"]>;
/** One row of the dashboard list (GET /job-targets). */
export type JobTargetSummary = DeepRequired<S["JobTargetSummary"]>;

// Library of saved job descriptions and CVs, and the Reports page (R1).
export type LibraryRename = S["LibraryRename"];
export type JobTargetMatchIn = S["JobTargetMatchIn"];
export type JobTargetMatch = DeepRequired<S["JobTargetMatch"]>;
export type ResumeMatch = DeepRequired<S["ResumeMatch"]>;
export type ReportItem = DeepRequired<S["ReportItem"]>;
export type ReportType = ReportItem["type"];

// The Questions page (QB-1 to QB-4).
export type BankCompany = DeepRequired<S["BankCompany"]>;
export type BankQuestion = DeepRequired<S["BankQuestion"]>;
export type QuestionList = DeepRequired<S["QuestionList"]>;
export type QuestionHints = DeepRequired<S["QuestionHints"]>;

// Gap analysis (real endpoints in apps/api gap, P6).
export type GapAnalysisStart = S["GapAnalysisStart"];
export type GapAnalysisOut = DeepRequired<S["GapAnalysisOut"]>;
export type GapStatus = S["GapStatus"];

// Debrief and progress (real endpoints in apps/api scoring, P8).
export type Debrief = DeepRequired<S["Debrief"]>;
export type DebriefStatus = Debrief["status"];
export type DebriefSession = DeepRequired<S["DebriefSession"]>;
export type PreviousSignal = DeepRequired<S["PreviousSignal"]>;
export type AnswersAtBar = DeepRequired<S["AnswersAtBar"]>;
export type JobProgress = DeepRequired<S["JobProgress"]>;
export type CompetencyTrend = DeepRequired<S["CompetencyTrend"]>;

// Billing and account (real endpoints in apps/api billing and account, P9).
export type Usage = DeepRequired<S["UsageOut"]>;
export type ModelUsage = S["ModelUsage"];
export type PlanOffer = S["PlanOut"];
export type ExportJob = DeepRequired<S["ExportOut"]>;
export type Profile = DeepRequired<S["ProfileOut"]>;
export type ProfileIn = S["ProfileIn"];
export type ExportStatus = S["ExportOut"]["status"];
export type ExitSurveyIn = S["ExitSurveyIn"];
export type ExitReason = S["ExitSurveyIn"]["reason"];
export type GotJob = S["ExitSurveyIn"]["got_job"];

// Shared contracts from strong_core.schemas.
export type JobPosting = DeepRequired<S["JobPosting"]>;
export type Resume = DeepRequired<S["Resume"]>;
export type GapAnalysis = DeepRequired<S["GapAnalysis"]>;
export type PlannedSession = DeepRequired<S["PlannedSession"]>;
/** CU-10: a recommended Custom session with a ready setup. */
export type CustomRecommendation = DeepRequired<S["CustomRecommendation"]>;
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
export type SessionChannel = S["SessionChannel"];
export type SessionRecord = DeepRequired<S["SessionRecord"]>;

// Target roles, interviews and readiness per interview (U06: TG-3, RH-1, RH-2).
export type SuggestedInterviews = DeepRequired<S["SuggestedInterviews"]>;
export type InterviewsCreate = S["InterviewsCreate"];
export type InterviewOut = DeepRequired<S["InterviewOut"]>;
export type InterviewWithReadiness = DeepRequired<S["InterviewWithReadiness"]>;
export type InterviewDetail = DeepRequired<S["InterviewDetail"]>;
export type InterviewTakeOut = DeepRequired<S["InterviewTakeOut"]>;
export type RoleOut = DeepRequired<S["RoleOut"]>;
export type RoleSummary = DeepRequired<S["RoleSummary"]>;
export type Rehearsals = DeepRequired<S["Rehearsals"]>;
export type RehearsalItem = DeepRequired<S["RehearsalItem"]>;
export type CreateSessionRequest = S["CreateSessionRequest"];
export type VoiceJoin = S["VoiceJoin"];
export type SubscriptionStatus = S["SubscriptionStatus"];

// Custom interview (docs/custom-interview-spec.md, CU-1 to CU-11).
export type StandardType = Exclude<InterviewType, "custom" | "recruiter_screen">;
export type CustomSessionSpec = DeepRequired<S["CustomSessionSpec"]>;
export type CustomCategory = DeepRequired<S["CustomCategory"]>;
export type CustomQuestion = DeepRequired<S["CustomQuestion"]>;
export type QuestionRefusal = S["QuestionRefusal"];
export type QuestionCheckRequest = S["QuestionCheckRequest"];
export type QuestionCheckOut = DeepRequired<S["QuestionCheckOut"]>;
export type CategoryFocus = DeepRequired<S["CategoryFocus"]>;
export type FocusSuggestions = DeepRequired<S["FocusSuggestions"]>;
export type SavedQuestionIn = S["SavedQuestionIn"];
export type SavedQuestionPatch = S["SavedQuestionPatch"];
export type SavedQuestion = DeepRequired<S["SavedQuestionOut"]>;
export type SessionSetup = DeepRequired<S["SessionSetup"]>;
export type DebriefQuestion = DeepRequired<S["DebriefQuestion"]>;
export type OwnQuestionPoint = DeepRequired<S["OwnQuestionPoint"]>;
export type CustomInterviewAccess = S["CustomInterviewAccess"];
