import { useEffect, useRef, type ReactNode } from "react";

import type { HireSignal } from "../api/types";
import { hireSignalTone, rubricLabel } from "../labels";
import { CheckBadge } from "./BrandMark";

const HIRE_SIGNALS: HireSignal[] = ["Strong Hire", "Hire", "Lean Hire", "Lean No Hire", "No Hire"];

/**
 * Page heading. Sets the document title and moves focus to the heading when the page opens,
 * so screen reader users hear where they are after each route change.
 */
export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} | Strong Hire`;
    ref.current?.focus();
  }, [title]);
  return (
    <header className="page-head">
      <h1 ref={ref} tabIndex={-1}>
        {title}
      </h1>
      {children}
    </header>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="loading" role="status">
      {label}
    </p>
  );
}

export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice notice--error" role="alert">
      {title && <p className="label">{title}</p>}
      <p>{message}</p>
    </div>
  );
}

export function Rubric({ score }: { score: number }) {
  return (
    <span className="rubric">
      <span className="rubric__marks" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => (
          <span key={n} data-on={n <= score} />
        ))}
      </span>
      <span>
        {score} of 4<span className="visually-hidden">, {rubricLabel[score]}</span>
      </span>
    </span>
  );
}

export function Bar({ value, label }: { value: number; label: string }) {
  return (
    <div className="bar" role="img" aria-label={label}>
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

/** The hire signal with the full five-step scale, so the result reads in context. */
export function HireSignalScale({ signal }: { signal: HireSignal }) {
  return (
    <>
      <div className="verdict__head">
        {(signal === "Hire" || signal === "Strong Hire") && <CheckBadge size={46} />}
        <p className="verdict__title" data-tone={hireSignalTone[signal]} data-testid="hire-signal">
          {signal}
        </p>
      </div>
      <ol className="ladder" aria-label="Hire signal scale, strongest first">
        {HIRE_SIGNALS.map((s) => (
          <li key={s} aria-current={s === signal ? "true" : undefined}>
            {s}
          </li>
        ))}
      </ol>
    </>
  );
}

export function Steps({ current, steps }: { current: number; steps: string[] }) {
  return (
    <ol className="steps" aria-label="Setup steps">
      {steps.map((name, i) => (
        <li
          key={name}
          aria-current={i === current ? "step" : undefined}
          data-state={i < current ? "done" : undefined}
        >
          {name}
          {i < current && <span className="visually-hidden"> (done)</span>}
        </li>
      ))}
    </ol>
  );
}

export const ONBOARDING_STEPS = ["Job posting", "Resume", "Context"];
