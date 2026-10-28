import { useEffect, useRef, type ReactNode } from "react";

import type { HireSignal } from "../api/types";
import { hireSignalTone, rubricLabel } from "../labels";
import { CheckBadge } from "./BrandMark";

const HIRE_SIGNALS: HireSignal[] = ["Strong Hire", "Hire", "Lean Hire", "Lean No Hire", "No Hire"];

/**
 * Page heading. Sets the document title and moves focus to the heading when the page opens,
 * so screen reader users hear where they are after each route change.
 */
export function PageHead({
  title,
  eyebrow,
  eyebrowTone,
  hidden = false,
  children,
}: {
  title: string;
  /** Keep the h1 (page title, focus on navigation) but hide it visually, where the canvas shows none. */
  hidden?: boolean;
  /** Optional mono line above the title, like "Interview prep". */
  eyebrow?: string;
  eyebrowTone?: "action" | "prep" | "muted";
  children?: ReactNode;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} | Strong Hire`;
    ref.current?.focus();
  }, [title]);
  return (
    <header className={hidden ? "page-head visually-hidden" : "page-head"}>
      {eyebrow && <Eyebrow tone={eyebrowTone}>{eyebrow}</Eyebrow>}
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

/* ------------------------------------------------------------ v2 shared pieces (UI-1) */

/** A small heading line above a page title, in mono caps. `tone` picks violet (stories) or teal (interview prep). */
export function Eyebrow({ children, tone = "action" }: { children: ReactNode; tone?: "action" | "prep" | "muted" }) {
  return (
    <p className="eyebrow" data-tone={tone}>
      {children}
    </p>
  );
}

export type StatusTone = "ok" | "warn" | "danger" | "neutral" | "action" | "prep";

/** A rounded status label, like "Proven", "Needs work" or "Draft". The text carries the meaning. */
export function StatusBadge({ tone = "neutral", children }: { tone?: StatusTone; children: ReactNode }) {
  return (
    <span className="status-badge" data-tone={tone}>
      {children}
    </span>
  );
}

/** A pill: a skill or topic chip. `state` follows the coverage colors on Home (strong, thin, gap). */
export function Pill({ children, state }: { children: ReactNode; state?: "strong" | "thin" | "gap" }) {
  return (
    <span className="pill" data-state={state}>
      {children}
    </span>
  );
}

/** A small outlined tag, for metadata like a round type or a difficulty. */
export function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}

/**
 * A segmented control: a small set of exclusive choices, like coaching style Gentle or Direct.
 * Each option is a toggle button with aria-pressed, inside a labeled group.
 */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A rubric meter, 1 to 4, with the score in text. Same data as Rubric, drawn as a bar of four steps. */
export function Meter({ score, label }: { score: number; label?: string }) {
  const s = Math.max(0, Math.min(4, Math.round(score)));
  return (
    <span className="meter" data-level={s >= 3 ? "ok" : s >= 1 ? "warn" : undefined}>
      {label && <span className="meter__label">{label}</span>}
      <span className="meter__steps" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => (
          <span key={n} data-on={n <= s} />
        ))}
      </span>
      <span className="meter__value">
        {s} of 4<span className="visually-hidden">, {rubricLabel[s] ?? ""}</span>
      </span>
    </span>
  );
}

export type StoryPart = "context" | "stakes" | "action" | "result" | "reflection";

export const STORY_PART_LABEL: Record<StoryPart, string> = {
  context: "Context",
  stakes: "Stakes",
  action: "Your action",
  result: "Result",
  reflection: "Reflection",
};

/** UI-1: one part of a story. Its color always comes with its name in text, never color alone. */
export function StoryPartChip({
  part,
  state,
  children,
}: {
  part: StoryPart;
  state?: "done" | "now" | "next";
  children?: ReactNode;
}) {
  return (
    <span className="story-part" data-part={part} data-state={state}>
      <span className="story-part__dot" aria-hidden="true" />
      {children ?? STORY_PART_LABEL[part]}
    </span>
  );
}

/** Days left until an interview, like "6 DAYS LEFT". Today and past dates read as words. */
export function CountdownBadge({ days }: { days: number }) {
  const text = days < 0 ? "Interview passed" : days === 0 ? "Today" : days === 1 ? "1 day left" : `${days} days left`;
  return (
    <span className="countdown" data-soon={days >= 0 && days <= 2 ? "true" : undefined}>
      {text}
    </span>
  );
}

/** The coach's mark: a violet ring with a dot. Decorative; the "Your coach" label names it. */
export function CoachMark({ size = 40, tone = "light" }: { size?: number; tone?: "light" | "dark" }) {
  return (
    <svg className="coach-mark" data-tone={tone} width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
      <circle cx={11} cy={11} r={10} fill="var(--coach-bg)" />
      <circle cx={11} cy={11} r={7} fill="none" stroke="var(--coach-fg)" strokeWidth={1.6} />
      <circle cx={11} cy={11} r={3.4} fill="var(--coach-fg)" />
    </svg>
  );
}

/** The coach's one-sentence message with its mark, as on Home and the debrief. */
export function CoachLine({
  children,
  label = "Your coach",
  tone = "light",
  actions,
}: {
  children: ReactNode;
  label?: string;
  tone?: "light" | "dark";
  actions?: ReactNode;
}) {
  return (
    <section className="coach-line" data-tone={tone} aria-label={label}>
      <CoachMark tone={tone} size={tone === "dark" ? 40 : 48} />
      <div className="coach-line__body">
        <p className="coach-line__label">{label}</p>
        <p className="coach-line__text">{children}</p>
        {actions && <div className="coach-line__actions">{actions}</div>}
      </div>
    </section>
  );
}
