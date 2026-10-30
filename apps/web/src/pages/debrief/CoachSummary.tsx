import type { AnswersAtBar, Scorecard } from "../../api/types";
import { CoachLine } from "../../components/ui";

/**
 * FB-1 rationale as the coach's message, with DB-2: how many answers met the bar. The mini and
 * Coach mode notes say why the session is not in the trends.
 */
export function CoachSummary({
  scorecard,
  atBar,
  mini,
  coach,
}: {
  scorecard: Scorecard;
  atBar: AnswersAtBar | null;
  mini: boolean;
  coach: boolean;
}) {
  const questions = scorecard.per_question.length;
  return (
    <div className="debrief-coach">
      <CoachLine tone="dark">{scorecard.rationale}</CoachLine>
      <dl className="debrief-coach__facts">
        {atBar && atBar.scored > 0 && (
          <div>
            <dt>Answers that met the bar</dt>
            <dd data-testid="answers-at-bar">
              {atBar.met} of {atBar.scored}
            </dd>
          </div>
        )}
      </dl>
      {mini && (
        <p className="debrief-coach__note" data-testid="mini-note">
          Mini interview. Based on {questions} {questions === 1 ? "question" : "questions"}. Practice signal only. It is
          not counted in your progress trends.
        </p>
      )}
      {coach && <p className="debrief-coach__note">Practice takes do not count toward readiness.</p>}
    </div>
  );
}
