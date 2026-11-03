/**
 * RSD-5: the shared card shell for the Resumes list and Target roles (spec D-2, D-3).
 *
 * A card is a `<section>` named by its title. It has a header (title and an optional chip), a row
 * of exactly three stat tiles, a muted meta line, an optional body, and a footer with the primary
 * link (Show details) on the left and the actions on the right. The card itself is never a link,
 * so the footer buttons never sit inside one, and the tiles are never interactive.
 */
import { useId, type ReactNode } from "react";
import { Link } from "react-router";

import "./ux.css";

export type StatTone = "neutral" | "warn" | "teal";

export interface StatTileProps {
  /** The number, or "—" when it is unknown. */
  value: number | string;
  /** The words under the number, for example "open issues". */
  label: string;
  tone?: StatTone;
  /** The spoken label of the ▲ mark on a `warn` tile, for example "Includes high-severity issues". */
  markLabel?: string;
}

/** The ▲ mark. Colour is never the only cue (00-common): it is an image with a spoken label. */
function WarnMark({ label }: { label: string }) {
  return (
    <svg className="sx-stat__mark" width="14" height="14" viewBox="0 0 14 14" role="img" aria-label={label}>
      <path d="M7 2 L13 12 H1 Z" fill="currentColor" />
    </svg>
  );
}

/**
 * One stat tile, inside a `<dl>`. The `<dt>` (label) comes first in the DOM so the pair reads
 * "label, value"; CSS shows the value on top.
 */
export function StatTile({ value, label, tone = "neutral", markLabel }: StatTileProps) {
  const unknown = value === "—";
  return (
    <div className={`sx-stat sx-stat--${tone}`} data-tone={tone}>
      <dt>{label}</dt>
      <dd className={unknown ? "sx-stat__value is-unknown" : "sx-stat__value"}>
        {tone === "warn" && markLabel ? <WarnMark label={markLabel} /> : null}
        {value}
      </dd>
    </div>
  );
}

export interface SummaryCardProps {
  /** The card's heading (an h2) and its accessible name. */
  title: ReactNode;
  /** An optional chip beside the title, for example Default or the interview date. */
  chip?: ReactNode;
  /** Exactly three tiles. */
  stats: readonly [StatTileProps, StatTileProps, StatTileProps];
  /** The muted line under the tiles, for example "Added Oct 28, 2026 · Edited Oct 28". */
  meta?: ReactNode;
  /** Optional body content, for example the readiness bars on a role. */
  children?: ReactNode;
  /** The primary link on the left of the footer (Show details). */
  primary?: ReactNode;
  /** Buttons on the right of the footer. */
  actions?: ReactNode;
  /** Draws empty tiles and hides the numbers (a resume Strova is still reading). */
  loading?: boolean;
  className?: string;
}

export function SummaryCard({
  title,
  chip,
  stats,
  meta,
  children,
  primary,
  actions,
  loading = false,
  className,
}: SummaryCardProps) {
  const headingId = useId();
  return (
    <section
      className={className ? `sx-summary ${className}` : "sx-summary"}
      aria-labelledby={headingId}
      aria-busy={loading || undefined}
    >
      <div className="sx-summary__head">
        <h2 id={headingId}>{title}</h2>
        {chip}
      </div>
      {loading ? (
        <div className="sx-summary__stats sx-summary__stats--loading" aria-hidden="true">
          <div className="sx-stat sx-stat--empty" />
          <div className="sx-stat sx-stat--empty" />
          <div className="sx-stat sx-stat--empty" />
        </div>
      ) : (
        <dl className="sx-summary__stats">
          {stats.map((s) => (
            <StatTile key={s.label} {...s} />
          ))}
        </dl>
      )}
      {meta ? <p className="sx-summary__meta">{meta}</p> : null}
      {children}
      {primary || actions ? (
        <div className="sx-summary__foot">
          {primary}
          {actions ? <div className="sx-summary__actions">{actions}</div> : null}
        </div>
      ) : null}
    </section>
  );
}

export interface AddCardProps {
  to: string;
  title: string;
  hint?: ReactNode;
}

/** The dashed "+ title / hint" link card that ends a grid (for example "Add a resume"). */
export function AddCard({ to, title, hint }: AddCardProps) {
  return (
    <Link className="sx-summary-add" to={to}>
      <span className="sx-summary-add__plus" aria-hidden="true">
        +
      </span>
      <strong>{title}</strong>
      {hint ? <span className="sx-small">{hint}</span> : null}
    </Link>
  );
}
