import type { Competency, CompetencyTrend, ProgressSnapshot } from "../api/types";
import { competencyLabel, formatDate } from "../labels";

const W = 220;
const H = 110;
const PAD = { top: 10, right: 12, bottom: 18, left: 22 };

/** One competency's Realistic-session scores (1 to 4) over time. Single series: no legend. */
/** "Up 1.0 since your first session". Display only: the API computes the change. */
export function trendText(t: CompetencyTrend | undefined): string | null {
  if (!t || t.direction === "single") return null;
  if (t.direction === "flat") return "No change since your first session";
  const word = t.direction === "up" ? "Up" : "Down";
  return `${word} ${Math.abs(t.change).toFixed(1)} since your first session`;
}

function TrendSmall({
  competency,
  points,
  trend,
}: {
  competency: Competency;
  points: ProgressSnapshot[];
  trend?: CompetencyTrend;
}) {
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (score: number) => PAD.top + ((4 - score) / 3) * innerH;
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ");
  const last = points.at(-1);
  const name = competencyLabel(competency);

  return (
    <figure className="trend-chart" style={{ margin: 0 }}>
      <figcaption className="row row--between">
        <span className="label">{name}</span>
        {last && <span className="muted">{last.score.toFixed(1)} of 4</span>}
      </figcaption>
      {trendText(trend) && <p className="muted">{trendText(trend)}</p>}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        role="img"
        aria-label={`${name}: ${points.map((p) => p.score.toFixed(1)).join(", ")} over ${points.length} sessions`}
      >
        {[1, 2, 3, 4].map((g) => (
          <g key={g}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(g)} y2={y(g)} stroke="var(--line)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(g) + 4} fontSize={10} textAnchor="end" fill="var(--muted)">
              {g}
            </text>
          </g>
        ))}
        {points.length > 1 && (
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        )}
        {points.map((p, i) => (
          <g key={p.session_id}>
            {/* Larger transparent hit target; the native tooltip shows the value. */}
            <circle cx={x(i)} cy={y(p.score)} r={10} fill="transparent">
              <title>{`${formatDate(p.at)}: ${p.score.toFixed(1)} of 4`}</title>
            </circle>
            <circle
              cx={x(i)}
              cy={y(p.score)}
              r={4}
              fill="var(--accent)"
              stroke="var(--surface)"
              strokeWidth={2}
              pointerEvents="none"
            />
          </g>
        ))}
      </svg>
    </figure>
  );
}

/** Competency scores grouped by competency, oldest first. */
function byCompetency(snapshots: ProgressSnapshot[]): [Competency, ProgressSnapshot[]][] {
  const map = new Map<Competency, ProgressSnapshot[]>();
  for (const s of [...snapshots].sort((a, b) => a.at.localeCompare(b.at))) {
    const list = map.get(s.competency) ?? [];
    list.push(s);
    map.set(s.competency, list);
  }
  return [...map.entries()];
}

const SW = 90;
const SH = 26;

/**
 * One small line per competency: ink line, dashed line at 3 (meets the bar), end point green at
 * 3.0 or more and amber below. The latest score is also written as a number next to it.
 */
function Sparkline({ name, points }: { name: string; points: ProgressSnapshot[] }) {
  const pad = 4;
  const x = (i: number) => (points.length === 1 ? SW / 2 : pad + (i / (points.length - 1)) * (SW - 2 * pad));
  const y = (score: number) => pad + ((4 - score) / 3) * (SH - 2 * pad);
  const last = points[points.length - 1];
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${SW} ${SH}`}
      width={SW}
      height={SH}
      role="img"
      aria-label={`${name}: ${points.map((p) => p.score.toFixed(1)).join(", ")}`}
    >
      <line x1={0} x2={SW} y1={y(3)} y2={y(3)} stroke="var(--line-strong)" strokeDasharray="2 3" />
      {points.length > 1 && (
        <polyline
          points={points.map((p, i) => `${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ")}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1.6}
          strokeLinejoin="round"
        />
      )}
      <circle
        cx={x(points.length - 1)}
        cy={y(last.score)}
        r={3.4}
        fill={last.score >= 3 ? "var(--ok)" : "var(--light)"}
        stroke="var(--surface)"
        strokeWidth={1.2}
      />
    </svg>
  );
}

/** PR-1, compact: one row per competency with a sparkline and the latest score. */
export function CompetencySparklines({ snapshots }: { snapshots: ProgressSnapshot[] }) {
  return (
    <ul className="sparklines">
      {byCompetency(snapshots).map(([competency, points]) => {
        const name = competencyLabel(competency);
        return (
          <li key={competency}>
            <span>{name}</span>
            <Sparkline name={name} points={points} />
            <span className="sparklines__value">{points[points.length - 1].score.toFixed(1)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** PR-1: competency trends from Realistic sessions, as small multiples with a table view. */
export function CompetencyTrends({ snapshots, trends = [] }: { snapshots: ProgressSnapshot[]; trends?: CompetencyTrend[] }) {
  const byCompetency = new Map<Competency, ProgressSnapshot[]>();
  for (const s of [...snapshots].sort((a, b) => a.at.localeCompare(b.at))) {
    const list = byCompetency.get(s.competency) ?? [];
    list.push(s);
    byCompetency.set(s.competency, list);
  }
  const entries = [...byCompetency.entries()];

  return (
    <div>
      <div className="row" style={{ alignItems: "flex-start", gap: "var(--space-5)" }}>
        {entries.map(([competency, points]) => (
          <TrendSmall
            key={competency}
            competency={competency}
            points={points}
            trend={trends.find((t) => t.competency === competency)}
          />
        ))}
      </div>
      <details>
        <summary>Show trends as a table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Competency</th>
              <th scope="col">Date</th>
              <th scope="col" className="num">
                Score (1 to 4)
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.flatMap(([competency, points]) =>
              points.map((p) => (
                <tr key={`${competency}-${p.session_id}`}>
                  <td>{competencyLabel(competency)}</td>
                  <td>{formatDate(p.at)}</td>
                  <td className="num">{p.score.toFixed(1)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </details>
    </div>
  );
}
