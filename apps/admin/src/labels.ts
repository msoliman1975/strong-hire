/** Display names for contract enum values (copied from apps/web). Display only: no rules here. */
import type { Difficulty, InterviewType, Mode, Phase } from "./api/types";

export const interviewTypeLabel: Record<InterviewType, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager deep dive",
  technical_qa: "Verbal technical Q&A",
  case: "Case",
  custom: "Custom",
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
