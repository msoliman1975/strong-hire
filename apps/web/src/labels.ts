/** Display names for contract enum values. Display only: no rules live here. */
import type {
  Competency,
  Difficulty,
  HireSignal,
  InterviewType,
  Level,
  Mode,
  Phase,
  RoleFamily,
  Severity,
} from "./api/types";

export const interviewTypeLabel: Record<InterviewType, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager deep dive",
  technical_qa: "Verbal technical Q&A",
  case: "Case",
};

export const interviewTypeHint: Record<InterviewType, string> = {
  behavioral: "Past situations: ownership, conflict, impact.",
  hiring_manager: "Your experience, judgment and fit for this team.",
  technical_qa: "Spoken technical questions. No live coding.",
  case: "Product sense, estimation or system thinking.",
};

export const difficultyLabel: Record<Difficulty, string> = {
  friendly: "Friendly",
  realistic: "Realistic",
  tough: "Tough",
};

export const difficultyHint: Record<Difficulty, string> = {
  friendly: "Patient interviewer, gentle follow-ups.",
  realistic: "Like a typical real interview.",
  tough: "Challenges your assumptions and pushes back.",
};

export const modeLabel: Record<Mode, string> = { coach: "Coach", realistic: "Realistic" };

export const modeHint: Record<Mode, string> = {
  coach: "Pause, ask for a hint, or redo an answer. Not counted in your trends.",
  realistic: "No interruptions. Counts toward your progress.",
};

export const levelLabel: Record<Level, string> = {
  new_grad: "New grad",
  mid: "Mid level",
  senior: "Senior",
  staff_principal: "Staff or principal",
};

export const roleFamilyLabel: Record<RoleFamily, string> = {
  swe: "Software engineering",
  data_ml: "Data and ML",
  pm: "Product management",
  design: "Design",
  tpm: "Technical program management",
  other: "Other",
};

export const severityLabel: Record<Severity, string> = { low: "Low", medium: "Medium", high: "High" };

export const phaseLabel: Record<Phase, string> = {
  intro: "Intro",
  small_talk: "Small talk",
  agenda: "Agenda",
  core: "Core questions",
  candidate_questions: "Your questions",
  wrap_up: "Wrap-up",
};

export const hireSignalTone: Record<HireSignal, "strong" | "positive" | "neutral" | "negative"> = {
  "Strong Hire": "strong",
  Hire: "positive",
  "Lean Hire": "neutral",
  "Lean No Hire": "negative",
  "No Hire": "negative",
};

export function competencyLabel(c: Competency): string {
  const text = c.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const rubricLabel: Record<number, string> = {
  1: "No evidence",
  2: "Weak",
  3: "Meets the bar",
  4: "Above the bar",
};

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * The product slogan next to the logo. Not agreed yet: while this is the placeholder,
 * the header does not show a slogan.
 */
export const SLOGAN = "{{SLOGAN}}";
export const hasSlogan = (s: string) => s.trim() !== "" && !s.startsWith("{{");
