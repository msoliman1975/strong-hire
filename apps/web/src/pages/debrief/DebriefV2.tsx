import "./debrief.css";

import type { ReactNode } from "react";
import { Link } from "react-router";

import type { Debrief, Scorecard } from "../../api/types";
import { RealismRating } from "../../components/RealismRating";
import { PageHead } from "../../components/ui";
import { difficultyLabel, formatDate, interviewTypeLabel, modeLabel } from "../../labels";
import { AnswerList } from "./AnswerList";
import { CoachSummary } from "./CoachSummary";
import { DeliveryMetrics } from "./DeliveryMetrics";
import { NextInPlan } from "./NextInPlan";
import { PracticeQuestions } from "./PracticeQuestions";
import { SignalCard } from "./SignalCard";

/** The notice under the verdict: the signal is practice, not a hiring prediction. */
export const PRACTICE_NOTICE =
  "The verdict is a practice estimate from an AI interviewer. It is not a prediction of any company's hiring decision.";

/**
 * The v2 debrief (canvas board B3), shown when `v2_enabled` is on and the scorecard is ready.
 * Each section is its own component in this folder, so later streams add theirs without editing
 * this layout: StoryUsed (S23) inside each answer, DeliveryMetrics (S24) under the answers.
 */
export function DebriefV2({
  debrief,
  scorecard,
  sideExtra,
}: {
  debrief: Debrief;
  scorecard: Scorecard;
  /** Custom sessions add their setup actions (CU-8, CU-9) here. */
  sideExtra?: ReactNode;
}) {
  const { session } = debrief;
  const { config } = session;
  const date = session.ended_at ?? session.started_at;
  return (
    <div className="debrief-v2">
      <PageHead
        eyebrow={debrief.company_name ? `${debrief.company_name} · Debrief` : "Debrief"}
        eyebrowTone="prep"
        title={`${interviewTypeLabel[config.interview_type]} · ${difficultyLabel[config.difficulty]} · ${config.duration_min} min`}
      >
        <p className="muted">
          {modeLabel[config.mode]} mode{date && `, ${formatDate(date)}`}
        </p>
        {/* TR-1 (S13). */}
        {session.ended_at && (
          <p>
            <Link to={`/sessions/${session.id}/transcript`}>Read the transcript</Link>
          </p>
        )}
      </PageHead>

      <section className="debrief-v2__verdict" aria-label="Verdict">
        <SignalCard signal={scorecard.hire_signal} previous={debrief.previous_signal} />
        <CoachSummary
          scorecard={scorecard}
          atBar={debrief.answers_at_bar}
          mini={config.duration_min === 10}
          coach={config.mode === "coach"}
        />
      </section>

      <div className="debrief-v2__body">
        <div className="debrief-v2__main">
          <AnswerList answers={scorecard.per_question} />
          <DeliveryMetrics scorecard={scorecard} />
        </div>
        <aside className="debrief-v2__side" aria-label="What to do next">
          <NextInPlan debrief={debrief} />
          {sideExtra}
          <PracticeQuestions debrief={debrief} />
          <RealismRating sessionId={session.id} />
          <p className="muted small" data-testid="practice-notice">
            {PRACTICE_NOTICE}
          </p>
        </aside>
      </div>
    </div>
  );
}
