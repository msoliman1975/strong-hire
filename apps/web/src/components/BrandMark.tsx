import type { CSSProperties } from "react";

/**
 * The Strong Hire logo, "the Approved h": a lamp, its light, the candidate's chair cut out of
 * the light in the shape of an "h", and the green check of an earned verdict.
 * Rules: never remove the check, never color the light green, never draw the chair on top of the light.
 */
export function BrandMark({ size = 30, tone = "light" }: { size?: number; tone?: "stage" | "light" }) {
  return (
    <svg
      className="brand-mark"
      data-tone={tone}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-label="Strong Hire"
    >
      <rect x={18} y={1.5} width={12} height={5} rx={1.5} fill="var(--brand-main)" />
      <path d="M19.5 6.5 L28.5 6.5 L42 44 L6 44 Z" fill="var(--light)" />
      <rect x={17} y={18} width={4.5} height={24} rx={1} fill="var(--brand-bg)" />
      <path
        d="M21.5 28.5 H26 A5.5 5.5 0 0 1 31.5 34 V42 H27 V34.5 A1.5 1.5 0 0 0 25.5 33 H21.5 Z"
        fill="var(--brand-bg)"
      />
      <circle cx={38} cy={38} r={9.5} fill="var(--brand-bg)" />
      <circle cx={38} cy={38} r={8} fill="var(--ok)" />
      <CheckPath d="M34 38.2 L36.8 41 L42 35.5" width={2.4} />
    </svg>
  );
}

/** The green check alone, for earned verdicts (Hire and Strong Hire). Decorative: the verdict word carries the meaning. */
export function CheckBadge({ size = 18, style }: { size?: number; style?: CSSProperties }) {
  return (
    <svg className="check-badge" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" style={style}>
      <circle cx={24} cy={24} r={22} fill="var(--ok)" />
      <CheckPath d="M13 24.6 L20.6 32.2 L35 17" width={6.4} />
    </svg>
  );
}

function CheckPath({ d, width }: { d: string; width: number }) {
  return <path d={d} fill="none" stroke="#ffffff" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />;
}
