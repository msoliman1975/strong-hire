/**
 * S12 mock helpers for the debrief deltas (DB-1, DB-2), shaped like the API in
 * apps/api/src/strong_api/scoring/router.py.
 */
import type { SessionRecord } from "../api/sessions";
import type { AnswersAtBar, PreviousSignal, Scorecard } from "../api/types";

const SIGNALS = ["Strong Hire", "Hire", "Lean Hire", "Lean No Hire", "No Hire"] as const;

/** DB-2: an answer meets the bar when its average rubric score is 3 or more. */
export function mockAnswersAtBar(card: Scorecard): AnswersAtBar {
  const averages = card.per_question.map((q) => q.scores.reduce((sum, s) => sum + s.score, 0) / q.scores.length);
  return { met: averages.filter((a) => a >= 3).length, scored: averages.length };
}

/** DB-1: the latest completed session of the same job that started earlier. The mock scorecards
 * are fixed per type, so the previous signal is one band lower to show a change. */
export function mockPreviousSignal(
  session: SessionRecord,
  card: Scorecard,
  sessions: SessionRecord[],
): PreviousSignal | null {
  const start = session.started_at ?? "";
  const earlier = sessions
    .filter((s) => s.job_target_id === session.job_target_id && s.id !== session.id && s.status === "completed")
    .filter((s) => (s.started_at ?? "") < start)
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))[0];
  if (!earlier) return null;
  const rank = Math.min(SIGNALS.indexOf(card.hire_signal) + 1, SIGNALS.length - 1);
  return {
    session_id: earlier.id,
    hire_signal: SIGNALS[rank],
    ended_at: earlier.ended_at,
    change: rank - SIGNALS.indexOf(card.hire_signal),
  };
}
