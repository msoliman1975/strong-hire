/**
 * RSD-8: the check page's step list. Four steps, each with its name, a count and one line; the
 * current one has `aria-current="step"`. The steps are views, not a wizard (D-6): any step opens at
 * any time, and the step is in the URL (`?step=`). No readiness bar (D-5).
 */
import type { ReactNode } from "react";

export type CheckStep = "journey" | "findings" | "stories" | "lines";
export const CHECK_STEPS: readonly CheckStep[] = ["journey", "findings", "stories", "lines"];
/** Onboarding (D-9) shows steps 1 and 2 only. */
export const ONBOARDING_STEPS: readonly CheckStep[] = ["journey", "findings"];

/** The step from `?step=`, or null when it is missing or not one this page shows. */
export function parseStep(value: string | null, onboarding: boolean): CheckStep | null {
  const steps = onboarding ? ONBOARDING_STEPS : CHECK_STEPS;
  return steps.find((s) => s === value) ?? null;
}

/** RSD-8, D-9: without `?step=`, findings when one is open, else the journey; onboarding opens on the journey. */
export const defaultStep = (openFindings: number, onboarding: boolean): CheckStep =>
  onboarding || openFindings === 0 ? "journey" : "findings";

export interface StepInfo {
  /** The count on the right, or null to show none. */
  count: number | null;
  /** The line under the name. */
  line: ReactNode;
}

const NAMES: Record<CheckStep, string> = {
  journey: "Your career journey",
  findings: "Strova's findings",
  stories: "Stories to tell in interviews",
  lines: "Stronger resume lines",
};

/** "Resume → Interview" and "Your stories → Resume": the direction of steps 3 and 4. */
const TAGS: Partial<Record<CheckStep, string>> = {
  stories: "Resume → Interview",
  lines: "Your stories → Resume",
};

export const stepName = (step: CheckStep) => NAMES[step];

export function StepList({
  steps,
  current,
  info,
  onSelect,
  footer,
}: {
  steps: readonly CheckStep[];
  current: CheckStep;
  info: Record<CheckStep, StepInfo>;
  onSelect: (step: CheckStep) => void;
  footer?: ReactNode;
}) {
  return (
    <div className="cvc-steps">
      <nav aria-label="Steps">
        <ol className="cvc-steps__list">
          {steps.map((step, n) => {
            const { count, line } = info[step];
            return (
              <li key={step}>
                <button
                  type="button"
                  className="cvc-step"
                  aria-current={step === current ? "step" : undefined}
                  onClick={() => onSelect(step)}
                  data-step={step}
                >
                  <span className="cvc-step__dot" aria-hidden="true">
                    {n + 1}
                  </span>
                  <span className="cvc-step__text">
                    <b className="cvc-step__name">{NAMES[step]}</b>
                    {TAGS[step] ? <span className="cvc-step__tag">{TAGS[step]}</span> : <span className="cvc-step__line">{line}</span>}
                  </span>
                  {count !== null ? (
                    <span className="cvc-step__num" aria-label={`${count} open`}>
                      {count}
                    </span>
                  ) : (
                    <span className="cvc-step__num cvc-step__num--go" aria-hidden="true">
                      ›
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
      {footer && <div className="cvc-card cvc-steps__foot">{footer}</div>}
    </div>
  );
}
