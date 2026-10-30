/**
 * R3 explainability: a small ⓘ next to a number or a status, opening one plain sentence. Built on
 * <details>, so it needs no script, works with the keyboard and a screen reader, and keeps the
 * strict CSP. `topic` names what it explains ("What's this: Readiness").
 */
export function Explain({ topic, children }: { topic: string; children: string }) {
  return (
    <details className="explain">
      <summary aria-label={`What's this: ${topic}`}>
        <span aria-hidden="true">i</span>
      </summary>
      <p className="explain__text" role="note">
        {children}
      </p>
    </details>
  );
}

/** The sentences, in one place, so the same thing is explained the same way everywhere. */
export const EXPLAIN = {
  readiness:
    "Readiness: how many of the skills this interview tests you have passed in Realistic rehearsals. It counts nothing from Practice mode, and it is a practice estimate, not a prediction.",
  proven:
    "Proven: a story turns Proven when a Realistic rehearsal answer that uses it meets the bar, a 3 of 4 on its skills.",
  takes:
    "A take is one telling of a story, typed or spoken, scored on the story's skills from 1 to 4. Shorter and stronger takes are the goal.",
  hireSignal:
    "Hire signal: the AI interviewer's overall call on this rehearsal, from No Hire to Strong Hire. It is a practice estimate, not a prediction of any company's decision.",
} as const;
