import type { CSSProperties } from "react";

/**
 * The Strong Hire mark (v2): an ink rounded square with a white check. On the dark live room the
 * colors swap. The wordmark "Strong Hire" sits next to it in text, never inside the SVG.
 * `tone="stage"` is the v1 name for the header tone and draws the same as `light`.
 */
export function BrandMark({ size = 26, tone = "light" }: { size?: number; tone?: "light" | "stage" | "dark" }) {
  const t = tone === "stage" ? "light" : tone;
  return (
    <svg
      className="brand-mark"
      data-tone={t}
      width={size}
      height={size}
      viewBox="0 0 26 26"
      role="img"
      aria-label="Strong Hire"
    >
      <rect x={1} y={1} width={24} height={24} rx={7} fill="var(--brand-main)" />
      <path
        d="M7 13.5 L11 17.5 L19 9"
        fill="none"
        stroke="var(--brand-bg)"
        strokeWidth={2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The green check alone, for earned verdicts (Hire and Strong Hire). Decorative: the verdict word carries the meaning. */
export function CheckBadge({ size = 18, style }: { size?: number; style?: CSSProperties }) {
  return (
    <svg className="check-badge" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" style={style}>
      <circle cx={24} cy={24} r={22} fill="var(--ok)" />
      <path
        d="M13 24.6 L20.6 32.2 L35 17"
        fill="none"
        stroke="#ffffff"
        strokeWidth={6.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
