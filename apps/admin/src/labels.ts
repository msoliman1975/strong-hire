/** Display names for contract enum values (copied from apps/web). Display only: no rules here. */
import type { SimBehavior, SimLevel, SimQuality, SimRunStatus } from "./api/sim";
import type { Difficulty, InterviewType, Mode, Phase, RoleFamily } from "./api/types";

export const interviewTypeLabel: Record<InterviewType, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager deep dive",
  technical_qa: "Verbal technical Q&A",
  case: "Case",
  custom: "Custom",
  recruiter_screen: "Recruiter screen",
};

export const difficultyLabel: Record<Difficulty, string> = {
  friendly: "Friendly",
  realistic: "Realistic",
  tough: "Tough",
};

export const modeLabel: Record<Mode, string> = { coach: "Coach", realistic: "Realistic" };

export const phaseLabel: Record<Phase, string> = {
  intro: "Intro",
  small_talk: "Small talk",
  agenda: "Agenda",
  core: "Core questions",
  candidate_questions: "Your questions",
  wrap_up: "Wrap-up",
};

export const simStatusLabel: Record<SimRunStatus, string> = {
  queued: "Queued",
  waiting: "Waiting",
  starting: "Starting",
  interviewing: "Interviewing",
  judging: "Judging",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const qualityLabel: Record<SimQuality, string> = { strong: "Strong", average: "Average", weak: "Weak" };

export const behaviorLabel: Record<SimBehavior, string> = {
  normal: "Normal",
  long_answers: "Long answers",
  one_line_answers: "One-line answers",
  off_topic: "Goes off topic",
  asks_to_repeat: "Asks to repeat",
  silent: "Goes silent",
  interrupts: "Interrupts",
  argues: "Argues",
  many_questions_back: "Many questions back",
  prompt_injection: "Prompt injection",
  drops_connection: "Drops the connection",
};

export const levelLabel: Record<SimLevel, string> = {
  new_grad: "New grad",
  mid: "Mid",
  senior: "Senior",
  staff_principal: "Staff / principal",
};

export const roleFamilyLabel: Record<RoleFamily, string> = {
  swe: "Software engineering",
  data_ml: "Data and ML",
  pm: "Product management",
  design: "Design",
  tpm: "Technical program management",
  other: "Other",
};
