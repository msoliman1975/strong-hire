/**
 * DB-3 (mockup #debrief): Strova's verdict, in the interviewer hat. The hire signal in its colour
 * with the change from the previous take (DB-1), the answers that met the bar (DB-2), the
 * interview's readiness, the rationale and the practice-estimate note.
 */
import type { AnswersAtBar, Debrief, HireSignal, InterviewDetail, PreviousSignal, Scorecard } from "../../api/types";
import { Strova } from "../../components/strova";

/** The notice under the verdict: the signal is practice, not a hiring prediction. */
export const PRACTICE_NOTICE =
  "The verdict is a practice estimate from an AI interviewer. It is not a prediction of any company's hiring decision.";

/** DB-1: the line under the hire signal. */
export function changeText(previous: PreviousSignal | null): string {
  if (!previous) return "Your first scored take for this interview.";
  if (previous.change > 0) return `Up from ${previous.hire_signal} last take`;
  if (previous.change < 0) return `Down from ${previous.hire_signal} last take`;
  return `The same as last take`;
}

export function signalClass(s: HireSignal): string {
  if (s === "Strong Hire" || s === "Hire") return "sx-signal-hire";
  if (s === "Lean Hire") return "sx-signal-lean";
  return "sx-signal-no";
}

export function StrovaVerdict({
  debrief,
  scorecard,
  interview,
  mini,
  coach,
}: {
  debrief: Debrief;
  scorecard: Scorecard;
  interview: InterviewDetail | null;
  mini: boolean;
  coach: boolean;
}) {
  const previous = debrief.previous_signal;
  const atBar: AnswersAtBar | null = debrief.answers_at_bar;
  const acting = interview?.interview.acting_as.text.replace(/^Strova is acting as /, "");
  const readiness = interview?.readiness.score ?? null;
  const questions = scorecard.per_question.length;
  return (
    <section className="sx-card interviewer debrief-verdict" aria-labelledby="debrief-verdict-heading">
      <div className="sx-row">
        <Strova mode="interviewing" size={72} />
        <div>
          <h2 id="debrief-verdict-heading">Strova's verdict</h2>
          {acting && <span className="sx-small sx-muted">Wearing the interviewer hat: {acting}</span>}
        </div>
      </div>
      <div className="sx-row debrief-verdict__facts">
        <div className="sx-stack">
          <span className="sx-small sx-muted">Hire signal</span>
          <span className={`debrief-verdict__signal ${signalClass(scorecard.hire_signal)}`} data-testid="hire-signal">
            {scorecard.hire_signal}
          </span>
          <span className="sx-small debrief-verdict__change" data-change={previous?.change ?? 0} data-testid="signal-change">
            {changeText(previous)}
          </span>
        </div>
        {atBar && atBar.scored > 0 && (
          <div className="sx-stack">
            <span className="sx-small sx-muted">Met the bar</span>
            <span className="sx-mono debrief-verdict__num" data-testid="answers-at-bar">
              {atBar.met} of {atBar.scored}
            </span>
          </div>
        )}
        {interview && (
          <div className="sx-stack">
            <span className="sx-small sx-muted">Readiness</span>
            <span className="sx-mono debrief-verdict__num" data-testid="readiness">
              {readiness ?? "—"}
            </span>
          </div>
        )}
      </div>
      <p className="debrief-verdict__rationale">{scorecard.rationale}</p>
      {mini && (
        <p className="sx-small sx-muted" data-testid="mini-note">
          Mini interview. Based on {questions} {questions === 1 ? "question" : "questions"}. Practice signal only. It is
          not counted in your progress trends.
        </p>
      )}
      {coach && <p className="sx-small sx-muted">Practice takes do not count toward readiness.</p>}
      <p className="sx-small sx-muted" data-testid="practice-notice">
        {PRACTICE_NOTICE}
      </p>
    </section>
  );
}
