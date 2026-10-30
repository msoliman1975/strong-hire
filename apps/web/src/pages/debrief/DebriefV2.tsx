import "./debrief.css";
import "../../components/ux/ux.css";

import type { ReactNode } from "react";
import { Link } from "react-router";

import { useInterview, useRoleInterviews } from "../../api/roles";
import type { Debrief, DebriefSession, InterviewDetail, Scorecard } from "../../api/types";
import { RealismRating } from "../../components/RealismRating";
import { formatDate, interviewTypeLabel, modeLabelV2 as modeLabel } from "../../labels";
import { interviewPath } from "../roles/shared";
import { AnswerList } from "./AnswerList";
import { DeliveryMetrics } from "./DeliveryMetrics";
import { NextInPlan } from "./NextInPlan";
import { PracticeQuestions } from "./PracticeQuestions";
import { StoryUpdates } from "./StoryUpdates";
import { StrovaCoaching } from "./StrovaCoaching";
import { StrovaVerdict } from "./StrovaVerdict";

export { PRACTICE_NOTICE } from "./StrovaVerdict";

/** The interview this take belongs to (RH-1): its role's interview of the same type with this take. */
export function useTakeInterview(session: DebriefSession): InterviewDetail | null {
  const interviews = useRoleInterviews(session.job_target_id);
  const sameType = (interviews.data ?? []).filter(
    (i) => i.interview.interview_type === session.config.interview_type,
  );
  const detail = useInterview(sameType[0]?.interview.id ?? "");
  return detail.data ?? null;
}

/**
 * The v2 debrief (mockup #debrief), shown when `v2_enabled` is on and the scorecard is ready:
 * Strova's verdict (DB-3), the answers, the delivery metrics (DM-2), then Strova's coaching with
 * this take's suggestions (DB-4 to DB-6). The plan, library, Questions and realism cards follow.
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
  const interview = useTakeInterview(session);
  const take = interview?.takes.find((t) => t.session_id === session.id)?.number ?? null;
  const eyebrow = [debrief.company_name, interviewTypeLabel[config.interview_type], "debrief"]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="sx-page debrief-v2">
      <div className="sx-between">
        <div className="sx-stack debrief-v2__head">
          <div className="sx-eyebrow teal">{eyebrow}</div>
          <h1>{take ? `Take ${take} with Strova` : "Your take with Strova"}</h1>
          <span className="sx-small sx-muted">
            {modeLabel[config.mode]} mode · {config.duration_min} minutes{date && ` · ${formatDate(date)}`}
          </span>
        </div>
        <div className="sx-row sx-small">
          {interview && <Link to={interviewPath(interview.interview.id)}>Back to the interview</Link>}
          {/* TR-1 (S13). */}
          {session.ended_at && <Link to={`/sessions/${session.id}/transcript`}>Read the transcript</Link>}
        </div>
      </div>

      <StrovaVerdict
        debrief={debrief}
        scorecard={scorecard}
        interview={interview}
        mini={config.duration_min === 10}
        coach={config.mode === "coach"}
      />

      <AnswerList answers={scorecard.per_question} />
      <DeliveryMetrics scorecard={scorecard} />

      <StrovaCoaching debrief={debrief} scorecard={scorecard} />

      <div className="sx-grid2 debrief-v2__more" aria-label="What to do next" role="region">
        <NextInPlan debrief={debrief} />
        <StoryUpdates sessionId={session.id} />
        {sideExtra}
        <PracticeQuestions debrief={debrief} />
        <RealismRating sessionId={session.id} />
      </div>
    </div>
  );
}
