/**
 * SV-11: readiness drawn as Strova's ring. A teal arc fills clockwise from the top toward the goal
 * tick; at or above the goal the arc turns green (an earned result, ux-spec section 4.1). With no
 * Realistic take yet the ring is an empty track. The number sits in the middle from 40 px up.
 * It is a meter: the value is in aria-valuenow and aria-valuetext, never in colour alone.
 */
const R = 19;
const C = 2 * Math.PI * R;
/** Below this size the number is left out (the caller shows it in text). */
export const RING_NUMBER_MIN_SIZE = 40;

export interface ReadinessRingProps {
  score: number | null;
  goal: number;
  /** Width and height in px. */
  size?: number;
  /** The meter's accessible name, for example "Behavioral readiness". */
  label: string;
}

export function readinessText(score: number | null, goal: number): string {
  if (score === null) return `Not started, goal ${goal}`;
  return `${score} of 100, goal ${goal}${score >= goal ? ", goal reached" : ""}`;
}

export function ReadinessRing({ score, goal, size = 56, label }: ReadinessRingProps) {
  const value = score === null ? 0 : Math.max(0, Math.min(100, score));
  const reached = score !== null && score >= goal;
  const angle = (goal / 100) * 2 * Math.PI - Math.PI / 2;
  const tick = (r: number) => [24 + r * Math.cos(angle), 24 + r * Math.sin(angle)].map((n) => n.toFixed(2));
  const [x1, y1] = tick(R - 3.5);
  const [x2, y2] = tick(R + 3);
  return (
    <svg
      className="sx-ring"
      data-state={score === null ? "empty" : reached ? "reached" : "below"}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-valuetext={readinessText(score, goal)}
    >
      <circle cx={24} cy={24} r={R} fill="none" className="sx-ring-track" strokeWidth={5} />
      {score !== null && value > 0 && (
        <circle
          cx={24}
          cy={24}
          r={R}
          fill="none"
          className="sx-ring-arc"
          strokeWidth={5}
          strokeLinecap="round"
          strokeDasharray={C.toFixed(2)}
          strokeDashoffset={(C * (1 - value / 100)).toFixed(2)}
          transform="rotate(-90 24 24)"
          data-part="arc"
        />
      )}
      {!reached && <line x1={x1} y1={y1} x2={x2} y2={y2} className="sx-ring-goal" strokeWidth={2} strokeLinecap="round" data-part="goal" />}
      {size >= RING_NUMBER_MIN_SIZE && (
        <text x={24} y={24} textAnchor="middle" dominantBaseline="central" className="sx-ring-num" aria-hidden="true">
          {score ?? "–"}
        </text>
      )}
    </svg>
  );
}
