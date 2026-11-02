import type { CSSProperties } from "react";

/**
 * The Strong Hire logo, "the Orbit" (SV-10): Strova's ring, open at the top right, and the
 * candidate as the green dot in the gap, on the way to the offer. The ring is Strova's coach
 * violet and the dot is the green of an earned verdict, so the logo and the agent share one shape.
 * The colors are the --brand-* variables on `.brand-mark` in styles.css (light, and dark for the
 * live room). The gap is drawn, never painted over, so the mark sits on any background.
 * Rules: never close the ring, never move the dot out of the gap, never color the dot violet.
 * The wordmark "Strong Hire" sits next to it in text, never inside the SVG.
 */
export const ORBIT_RING = "M41.56 20.03 A18 18 0 1 1 27.97 6.44";
export const ORBIT_DOT = { cx: 36.73, cy: 11.27, r: 5.5 } as const;

export function BrandMark({ size = 26, tone = "light" }: { size?: number; tone?: "light" | "stage" | "dark" }) {
  const t = tone === "stage" ? "light" : tone;
  return (
    <svg
      className="brand-mark"
      data-tone={t}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-label="Strong Hire"
    >
      <path
        d={ORBIT_RING}
        fill="none"
        stroke="var(--brand-ring)"
        strokeWidth={5}
        strokeLinecap="round"
        data-part="ring"
      />
      <circle {...ORBIT_DOT} fill="var(--brand-dot)" data-part="dot" />
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
