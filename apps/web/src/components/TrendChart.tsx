import type { Competency, ProgressSnapshot } from "../api/types";
import { competencyLabel, formatDate } from "../labels";

const W = 220;
const H = 110;
const PAD = { top: 10, right: 12, bottom: 18, left: 22 };

/** One competency's Realistic-session scores (1 to 4) over time. Single series: no legend. */
function TrendSmall({ competency, points }: { competency: Competency; points: ProgressSnapshot[] }) {
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

/** PR-1: competency trends from Realistic sessions, as small multiples with a table view. */
export function CompetencyTrends({ snapshots }: { snapshots: ProgressSnapshot[] }) {
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
          <TrendSmall key={competency} competency={competency} points={points} />
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
