/** U05: the three first-run steps in the top bar: Profile · Your resume · Plan style. */
const STEPS = ["Profile", "Your resume", "Plan style"] as const;

export function StartSteps({ step }: { step: 1 | 2 | 3 }) {
  return (
    <ol className="sx-steps" aria-label="Setup steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const state = n < step ? "done" : n === step ? "on" : undefined;
        return (
          <li key={label} className={state} aria-current={n === step ? "step" : undefined}>
            {state === "done" && <span className="visually-hidden">Done: </span>}
            {label}
          </li>
        );
      })}
    </ol>
  );
}
