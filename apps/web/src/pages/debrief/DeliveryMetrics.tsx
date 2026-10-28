import "./DeliveryMetrics.css";

import type { QuestionScore, Scorecard } from "../../api/types";

/**
 * DM-2: what counts as a normal delivery, in one place.
 *
 * - Pace: conversational English runs at about 120 to 160 words per minute. Interview answers
 *   are a little slower while people think, so 110 to 170 is treated as normal. Below sounds
 *   hesitant; above is hard to follow on a call.
 * - Fillers: a few per minute go unnoticed. Above 5 per minute ("um", "uh", "you know" ...)
 *   listeners start to hear them.
 *
 * The metrics come from the worker (strong_worker.scoring.delivery), from the transcript's text and
 * timestamps; no audio is used.
 */
export const DELIVERY_RANGES = {
  paceMinWpm: 110,
  paceMaxWpm: 170,
  fillersMaxPerMin: 5,
} as const;

export const NO_DELIVERY_NOTE =
  "Pace and filler words are measured from spoken answers. This session has none to measure, for example because it was typed.";

/** The plain notes for one answer, empty when everything is within the normal range. */
export function deliveryNotes(d: NonNullable<QuestionScore["delivery"]>): string[] {
  const notes: string[] = [];
  if (d.words_per_minute < DELIVERY_RANGES.paceMinWpm) {
    notes.push(
      `Slower than usual (normal is ${DELIVERY_RANGES.paceMinWpm} to ${DELIVERY_RANGES.paceMaxWpm} words a minute). Try shorter pauses between points.`,
    );
  } else if (d.words_per_minute > DELIVERY_RANGES.paceMaxWpm) {
    notes.push(
      `Faster than usual (normal is ${DELIVERY_RANGES.paceMinWpm} to ${DELIVERY_RANGES.paceMaxWpm} words a minute). Slow down so the interviewer can follow.`,
    );
  }
  if (d.fillers_per_minute > DELIVERY_RANGES.fillersMaxPerMin) {
    notes.push(
      `More filler words than usual (over ${DELIVERY_RANGES.fillersMaxPerMin} a minute). A short silence works better than "um".`,
    );
  }
  return notes;
}

function paceOutOfRange(wpm: number): boolean {
  return wpm < DELIVERY_RANGES.paceMinWpm || wpm > DELIVERY_RANGES.paceMaxWpm;
}

function round(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function duration(seconds: number): string {
  const s = Math.round(seconds);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

/** DM-2: pace and fillers per answer, under the answers on the v2 debrief. */
export function DeliveryMetrics({ scorecard }: { scorecard: Scorecard }) {
  const answers = scorecard.per_question;
  const measured = answers.filter((q) => q.delivery);
  return (
    <section className="debrief-delivery" aria-labelledby="debrief-delivery-heading">
      <h2 id="debrief-delivery-heading">Delivery</h2>
      {measured.length === 0 ? (
        <p className="muted" data-testid="delivery-none">
          {NO_DELIVERY_NOTE}
        </p>
      ) : (
        <ol className="plain-list debrief-delivery__list">
          {answers.map((q, i) => (
            <DeliveryRow key={q.question_ref} answer={q} index={i + 1} />
          ))}
        </ol>
      )}
    </section>
  );
}

function DeliveryRow({ answer, index }: { answer: QuestionScore; index: number }) {
  const d = answer.delivery;
  const notes = d ? deliveryNotes(d) : [];
  return (
    <li className="card debrief-delivery__item" data-testid="delivery">
      <p className="debrief-delivery__question">
        <span className="muted">Answer {index}.</span> {answer.question_text}
      </p>
      {d ? (
        <>
          <dl className="debrief-delivery__stats">
            <div data-out={paceOutOfRange(d.words_per_minute) ? "true" : undefined}>
              <dt>Pace</dt>
              <dd>{round(d.words_per_minute)} words a minute</dd>
            </div>
            <div data-out={d.fillers_per_minute > DELIVERY_RANGES.fillersMaxPerMin ? "true" : undefined}>
              <dt>Fillers</dt>
              <dd>{round(d.fillers_per_minute)} a minute</dd>
            </div>
            <div>
              <dt>Speaking time</dt>
              <dd>{duration(d.duration_seconds)}</dd>
            </div>
          </dl>
          {notes.map((n) => (
            <p key={n} className="debrief-delivery__note" data-testid="delivery-note">
              {n}
            </p>
          ))}
        </>
      ) : (
        <p className="muted small">Not measured: no spoken answer for this question.</p>
      )}
    </li>
  );
}
