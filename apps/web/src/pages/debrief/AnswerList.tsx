import type { QuestionScore } from "../../api/types";
import { StoryUsed } from "./StoryUsed";

/** DB-2: an answer meets the bar when its average rubric score is 3 or more. */
export const BAR_SCORE = 3;

export function answerAverage(q: QuestionScore): number | null {
  if (q.scores.length === 0) return null;
  return q.scores.reduce((sum, s) => sum + s.score, 0) / q.scores.length;
}

/** The transcript quote shown under the question: the first one the scorer gave for it. */
export function answerQuote(q: QuestionScore): string | null {
  return q.scores.find((s) => s.quotes.length > 0)?.quotes[0] ?? null;
}

/**
 * FB-2 on the v2 debrief: each answer with its score, a quote, and the one thing to fix (or what
 * to keep when nothing was missing).
 */
export function AnswerList({ answers }: { answers: QuestionScore[] }) {
  return (
    <section className="sx-card debrief-answers" aria-labelledby="debrief-answers-heading">
      <h2 id="debrief-answers-heading">Answer by answer</h2>
      <ol className="plain-list debrief-answers__list">
        {answers.map((q, i) => (
          <AnswerCard key={q.question_ref} answer={q} number={i + 1} />
        ))}
      </ol>
    </section>
  );
}

function AnswerCard({ answer, number }: { answer: QuestionScore; number: number }) {
  const avg = answerAverage(answer);
  const quote = answerQuote(answer);
  const fix = answer.misses[0] ?? null;
  const kept = answer.strengths[0] ?? null;
  const met = avg !== null && avg >= BAR_SCORE;
  return (
    <li className="sx-list-row debrief-answer" data-testid="answer">
      <div className="debrief-answer__head">
        <h3>
          <span className="debrief-answer__num" aria-hidden="true">
            {number}.{" "}
          </span>
          {answer.question_text}
        </h3>
        {avg !== null && (
          <span className="debrief-answer__score" data-met={met ? "true" : undefined}>
            {Number.isInteger(avg) ? avg : avg.toFixed(1)} of 4
          </span>
        )}
      </div>
      <StoryUsed answer={answer} />
      {quote && <blockquote className="debrief-answer__quote">“{quote}”</blockquote>}
      {fix ? (
        <p>
          <b>Fix:</b> {fix}
        </p>
      ) : (
        kept && (
          <p>
            <b>Kept:</b> {kept}
          </p>
        )
      )}
    </li>
  );
}
