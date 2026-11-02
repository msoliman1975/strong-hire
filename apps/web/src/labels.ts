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
  RolePlayScenario,
  Severity,
} from "./api/types";

export const interviewTypeLabel: Record<InterviewType, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager deep dive",
  technical_qa: "Verbal technical Q&A",
  case: "Case",
  custom: "Custom",
  recruiter_screen: "Recruiter screen",
  role_play: "Role-play",
};

export const interviewTypeHint: Record<InterviewType, string> = {
  behavioral: "Past situations: ownership, conflict, impact.",
  hiring_manager: "Your experience, judgment and fit for this team.",
  technical_qa: "Spoken technical questions. No live coding.",
  case: "Product sense, estimation or system thinking.",
  custom: "Mix question types, pick focus topics and add your own questions.",
  recruiter_screen: "Why this role, your background, and pay and timing.",
  role_play: "A mock sales or customer call: Strova plays the buyer or customer and you lead.",
};

/** RP-4, D-5, CS-1: the calls a role-play simulates: four sales calls and the escalation call. */
export const rolePlayScenarioLabel: Record<RolePlayScenario, string> = {
  cold_call: "Cold call",
  discovery_call: "Discovery call",
  demo_objections: "Demo and objections",
  negotiation_close: "Negotiation and close",
  escalation_call: "Escalation call",
};

export const rolePlayScenarioHint: Record<RolePlayScenario, string> = {
  cold_call: "The buyer did not expect your call. Earn a few minutes, then a meeting.",
  discovery_call: "A booked first call. Uncover the buyer's problems and agree a next step.",
  demo_objections: "Show how the product fixes the buyer's problems and handle pushback.",
  negotiation_close: "The buyer likes it. Handle price pushback and get a commitment.",
  escalation_call: "An upset customer and a renewal at risk. Calm the call, find the cause, agree a plan.",
};

/**
 * RP D-5, CS D-6: the default call. Customer success gets the escalation call at every level;
 * other families get a sales call by level.
 */
export function defaultRolePlayScenario(
  level: Level | null | undefined,
  family?: RoleFamily | null,
): RolePlayScenario {
  if (family === "customer_success") return "escalation_call";
  if (level === "new_grad") return "cold_call";
  if (level === "senior" || level === "staff_principal") return "demo_objections";
  return "discovery_call";
}

/** RP-8, CS D-7: who the candidate plays in the live room. */
export function rolePlayPart(scenario: RolePlayScenario | null | undefined): string {
  return scenario === "escalation_call" ? "the customer success manager" : "the seller";
}

/** D-11: the interview types still labeled Beta (fewer than 5 gold transcripts). */
export const betaInterviewTypes: ReadonlySet<InterviewType> = new Set<InterviewType>(["role_play"]);

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

/** RH-5: the v2 mode labels. The stored value stays `coach`; only the label is Practice. */
export const modeLabelV2: Record<Mode, string> = { coach: "Practice", realistic: "Realistic" };

export const modeHintV2: Record<Mode, string> = {
  coach: "Pause, ask for a hint, or redo an answer. Does not count toward readiness.",
  realistic: "No interruptions, like the real interview. Counts toward readiness.",
};

/** The mode labels for the screen: v2 says Practice, v1 keeps Coach. */
export function modeLabels(v2: boolean): { label: Record<Mode, string>; hint: Record<Mode, string> } {
  return v2 ? { label: modeLabelV2, hint: modeHintV2 } : { label: modeLabel, hint: modeHint };
}

export const levelLabel: Record<Level, string> = {
  new_grad: "New grad",
  mid: "Mid level",
  senior: "Senior",
  staff_principal: "Staff or principal",
};

export const roleFamilyLabel: Record<RoleFamily, string> = {
  swe: "Software engineering",
  infra_security: "Infrastructure and security",
  data_ml: "Data science and ML",
  data_analytics: "Data analytics",
  pm: "Product management",
  design: "Design",
  tpm: "Technical program management",
  eng_management: "Engineering management",
  finance: "Finance",
  consulting_strategy: "Consulting and strategy",
  project_program: "Project and program management",
  sales: "Sales",
  customer_success: "Customer success",
  other: "Other",
};

/**
 * RF-14: wave 1 families with fewer than 5 gold transcripts in evals/transcripts. The target role
 * page labels them Beta. A test (packages/core/tests/test_role_families.py) keeps this in step.
 */
export const betaRoleFamilies: ReadonlySet<RoleFamily> = new Set<RoleFamily>([
  "infra_security",
  "data_analytics",
  "eng_management",
  "finance",
  "consulting_strategy",
  "project_program",
  "sales",
  "customer_success",
]);

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
