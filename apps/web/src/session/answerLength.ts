/**
 * LR-1: how long the current answer has run, against a suggested length for the interview type.
 * An answer starts when the interviewer starts listening and ends when it starts thinking.
 */
import { useCallback, useState } from "react";

import type { InterviewType } from "../api/types";
import type { AgentActivity } from "./voice";

/** Suggested answer length in seconds per interview type. The one place these lengths live. */
export const SUGGESTED_ANSWER_SECONDS: Record<InterviewType, number> = {
  behavioral: 120,
  hiring_manager: 120,
  technical_qa: 90,
  case: 180,
  custom: 120,
  recruiter_screen: 60,
};

export interface AnswerTiming {
  /** Date.now() when the candidate's turn began. */
  startedAt: number;
  /** Date.now() when it ended, or null while the candidate is still answering. */
  endedAt: number | null;
}

/** The next answer timing after the interviewer's activity changes. */
export function nextTiming(
  timing: AnswerTiming | null,
  previous: AgentActivity,
  activity: AgentActivity,
  now: number,
): AnswerTiming | null {
  if (activity === "listening" && previous !== "listening") return { startedAt: now, endedAt: null };
  if (activity === "thinking" && timing && timing.endedAt === null) return { ...timing, endedAt: now };
  if (activity === "speaking") return null;
  return timing;
}

/**
 * The interviewer's activity and the current answer's timing. Pass `onActivity` to the voice
 * connection in place of a plain state setter.
 */
export function useActivityTiming(): {
  activity: AgentActivity;
  timing: AnswerTiming | null;
  onActivity: (activity: AgentActivity) => void;
} {
  const [state, setState] = useState<{ activity: AgentActivity; timing: AnswerTiming | null }>({
    activity: "idle",
    timing: null,
  });
  const onActivity = useCallback((activity: AgentActivity) => {
    const now = Date.now();
    setState((s) =>
      s.activity === activity ? s : { activity, timing: nextTiming(s.timing, s.activity, activity, now) },
    );
  }, []);
  return { ...state, onActivity };
}

/** Seconds the answer has run at `now`. */
export function answerSeconds(timing: AnswerTiming, now: number): number {
  return Math.max(0, Math.floor(((timing.endedAt ?? now) - timing.startedAt) / 1000));
}

export const minSec = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
