import type { HireSignal, PreviousSignal } from "../../api/types";
import { EXPLAIN, Explain } from "../../components/Explain";
import { formatDate, hireSignalTone } from "../../labels";

/** Weakest first, as on the canvas: the scale reads left to right toward Strong Hire. */
const SCALE: HireSignal[] = ["No Hire", "Lean No Hire", "Lean Hire", "Hire", "Strong Hire"];

/** DB-1: the sentence under the scale. */
export function changeText(previous: PreviousSignal | null): string {
  if (!previous) return "Your first scored session for this interview.";
  const when = previous.ended_at ? ` on ${formatDate(previous.ended_at)}` : "";
  if (previous.change > 0) return `Up from ${previous.hire_signal}${when} (dashed).`;
  if (previous.change < 0) return `Down from ${previous.hire_signal}${when} (dashed).`;
  return `The same as your last session${when}.`;
}

/**
 * FB-1 and DB-1: the hire signal on its five-step scale, with the previous session's signal for
 * the same job marked dashed and the change in words.
 */
export function SignalCard({ signal, previous }: { signal: HireSignal; previous: PreviousSignal | null }) {
  const before = previous && previous.change !== 0 ? previous.hire_signal : null;
  const label = `Hire signal scale: ${signal}${before ? `, previous ${before}` : ""}`;
  return (
    <section className="card debrief-signal" aria-labelledby="debrief-signal-heading">
      <div className="explain-head">
        <h2 id="debrief-signal-heading" className="debrief-signal__label">
          Hire signal
        </h2>
        <Explain topic="Hire signal">{EXPLAIN.hireSignal}</Explain>
      </div>
      <p className="debrief-signal__value" data-tone={hireSignalTone[signal]} data-testid="hire-signal">
        {signal}
      </p>
      <ol className="debrief-scale" aria-label={label}>
        {SCALE.map((s) => (
          <li
            key={s}
            aria-current={s === signal ? "true" : undefined}
            data-tone={s === signal ? hireSignalTone[s] : undefined}
            data-previous={s === before ? "true" : undefined}
          >
            {s === "Lean No Hire" ? "Lean No" : s}
          </li>
        ))}
      </ol>
      <p className="debrief-signal__change" data-testid="signal-change">
        {changeText(previous)}
      </p>
    </section>
  );
}
