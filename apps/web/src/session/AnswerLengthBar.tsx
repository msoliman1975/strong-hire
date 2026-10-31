import { answerSeconds, minSec, type AnswerTiming } from "./answerLength";

/**
 * LR-1: the bar under the interview. It fills toward the suggested length and turns amber past
 * it. Before the first answer it says when it starts.
 */
export function AnswerLengthBar({
  label = "Answer length",
  timing,
  suggestedSeconds,
  now,
}: {
  /** The row's label; the v2 room (mockup #live) says "Your answer". */
  label?: string;
  timing: AnswerTiming | null;
  suggestedSeconds: number;
  now: number;
}) {
  const seconds = timing ? answerSeconds(timing, now) : 0;
  const share = Math.min(1, seconds / suggestedSeconds);
  const over = seconds > suggestedSeconds;
  return (
    <section className="answer-length" aria-label="Answer length" data-testid="answer-length">
      <div className="answer-length__row">
        <span>{label}</span>
        <span className="answer-length__time" data-testid="answer-length-time">
          {timing ? `${minSec(seconds)} of about ${minSec(suggestedSeconds)}` : `About ${minSec(suggestedSeconds)}`}
        </span>
      </div>
      <div className="answer-length__track" aria-hidden="true">
        <span style={{ width: `${share * 100}%` }} data-over={over ? "true" : undefined} />
      </div>
      {over && (
        <p className="answer-length__hint" role="status">
          Past the suggested length. Wrap up with the result.
        </p>
      )}
    </section>
  );
}
