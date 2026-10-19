/**
 * Small inline SVG charts (no chart library): a sparkline, a line chart with a hover crosshair,
 * and a stacked bar chart with a hover tooltip. Colors are CSS tokens (--series-N, light and
 * dark in styles.css); every multi-series chart has a legend and a table view.
 */
import { useId, useState, type ReactNode } from "react";

export interface Point {
  t: string;
  v: number | null;
}

export interface LineSeries {
  key: string;
  label: string;
  points: Point[];
}

const W = 640;
const PAD = { top: 12, right: 12, bottom: 22, left: 48 };

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(value));
  const n = value / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

function shortTime(t: string, spanMs: number): string {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  const iso = d.toISOString();
  return spanMs > 2 * 86_400_000 ? iso.slice(5, 10) : iso.slice(11, 16);
}

/** A tiny line of recent values, for tiles and table rows. */
export function Sparkline({
  values,
  label,
  width = 120,
  height = 28,
}: {
  values: (number | null)[];
  label: string;
  width?: number;
  height?: number;
}) {
  const nums = values.filter((v): v is number => v !== null);
  if (nums.length === 0) return <span className="muted">No data</span>;
  const max = Math.max(...nums);
  const min = Math.min(0, ...nums);
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const d = values
    .map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <title>{label}</title>
      <polyline points={d} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}

function Legend({ items }: { items: { key: string; label: string }[] }) {
  return (
    <ul className="legend">
      {items.map((s, i) => (
        <li key={s.key}>
          <span className="legend__swatch" style={{ background: `var(--series-${i + 1})` }} aria-hidden="true" />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function DataTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="chart-table">
      <summary>Show as a table</summary>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {head.map((h, i) => (
                <th key={h} scope="col" className={i > 0 ? "num" : undefined}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} className={j > 0 ? "num" : undefined}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Lines over time on one axis. Series share the time points of the first series. */
export function LineChart({
  series,
  title,
  format,
  height = 180,
  target,
}: {
  series: LineSeries[];
  title: string;
  format: (v: number) => string;
  height?: number;
  target?: { value: number; label: string };
}) {
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const times = [...new Set(series.flatMap((s) => s.points.map((p) => p.t)))].sort();
  const all = series.flatMap((s) => s.points.map((p) => p.v)).filter((v): v is number => v !== null);
  if (times.length === 0 || all.length === 0) return <p className="muted">No data in this range.</p>;
  const max = niceMax(Math.max(...all, target?.value ?? 0));
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (times.length > 1 ? (i / (times.length - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const spanMs = Date.parse(times[times.length - 1]) - Date.parse(times[0]);
  const byTime = series.map((s) => new Map(s.points.map((p) => [p.t, p.v])));
  const ticks = [0, max / 2, max];
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = times.length > 1 ? Math.round(((px - PAD.left) / innerW) * (times.length - 1)) : 0;
    setHover(Math.max(0, Math.min(times.length - 1, i)));
  };
  return (
    <figure className="chart">
      <figcaption id={titleId} className="chart__title">
        {title}
      </figcaption>
      {series.length > 1 && <Legend items={series} />}
      <div className="chart__plot">
        <svg
          viewBox={`0 0 ${W} ${height}`}
          role="img"
          aria-labelledby={titleId}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="chart__grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="chart__tick" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">
                {format(t)}
              </text>
            </g>
          ))}
          <text className="chart__tick" x={PAD.left} y={height - 4}>
            {shortTime(times[0], spanMs)}
          </text>
          <text className="chart__tick" x={W - PAD.right} y={height - 4} textAnchor="end">
            {shortTime(times[times.length - 1], spanMs)}
          </text>
          {target && target.value <= max && (
            <g>
              <line className="chart__target" x1={PAD.left} x2={W - PAD.right} y1={y(target.value)} y2={y(target.value)} />
              <text className="chart__tick" x={W - PAD.right} y={y(target.value) - 4} textAnchor="end">
                {target.label}
              </text>
            </g>
          )}
          {series.map((s, si) => {
            const pts = times
              .map((t, i) => {
                const v = byTime[si].get(t);
                return v === null || v === undefined ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`;
              })
              .filter(Boolean);
            const color = `var(--series-${si + 1})`;
            return pts.length === 1 ? (
              <circle key={s.key} cx={pts[0]!.split(",")[0]} cy={pts[0]!.split(",")[1]} r={4} fill={color} />
            ) : (
              <polyline key={s.key} points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
            );
          })}
          {hover !== null && (
            <line className="chart__cross" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} />
          )}
        </svg>
        {hover !== null && (
          <div className="chart__tip" style={{ left: `${(x(hover) / W) * 100}%` }} role="status">
            <p className="label">{new Date(times[hover]).toISOString().slice(0, 16).replace("T", " ")} UTC</p>
            {series.map((s, si) => {
              const v = byTime[si].get(times[hover]);
              return (
                <p key={s.key}>
                  <span className="legend__swatch" style={{ background: `var(--series-${si + 1})` }} aria-hidden="true" />
                  {s.label}: {v === null || v === undefined ? "-" : format(v)}
                </p>
              );
            })}
          </div>
        )}
      </div>
      <DataTable
        head={["Time (UTC)", ...series.map((s) => s.label)]}
        rows={times.map((t, i) => [
          new Date(t).toISOString().slice(0, 16).replace("T", " "),
          ...series.map((_, si) => {
            const v = byTime[si].get(times[i]);
            return v === null || v === undefined ? "-" : format(v);
          }),
        ])}
      />
    </figure>
  );
}

export interface StackBar {
  label: string;
  parts: number[];
}

/** Stacked bars (for example cost per day by component), with a tooltip per bar. */
export function StackedBars({
  bars,
  parts,
  title,
  format,
  height = 180,
}: {
  bars: StackBar[];
  parts: string[];
  title: string;
  format: (v: number) => string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  if (bars.length === 0) return <p className="muted">No data in this range.</p>;
  const totals = bars.map((b) => b.parts.reduce((a, v) => a + v, 0));
  const max = niceMax(Math.max(...totals));
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const slot = innerW / bars.length;
  const bw = Math.max(4, Math.min(28, slot - 4));
  const y = (v: number) => (v / max) * innerH;
  return (
    <figure className="chart">
      <figcaption id={titleId} className="chart__title">
        {title}
      </figcaption>
      <Legend items={parts.map((p) => ({ key: p, label: p }))} />
      <div className="chart__plot">
        <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-labelledby={titleId} onMouseLeave={() => setHover(null)}>
          {[0, max / 2, max].map((t) => (
            <g key={t}>
              <line className="chart__grid" x1={PAD.left} x2={W - PAD.right} y1={PAD.top + innerH - y(t)} y2={PAD.top + innerH - y(t)} />
              <text className="chart__tick" x={PAD.left - 6} y={PAD.top + innerH - y(t) + 4} textAnchor="end">
                {format(t)}
              </text>
            </g>
          ))}
          {bars.map((b, i) => {
            const cx = PAD.left + slot * i + slot / 2;
            let base = PAD.top + innerH;
            return (
              <g key={b.label} onMouseEnter={() => setHover(i)}>
                <rect x={cx - slot / 2} y={PAD.top} width={slot} height={innerH} fill="transparent" />
                {b.parts.map((v, pi) => {
                  const h = y(v);
                  base -= h;
                  return h > 0 ? (
                    <rect
                      key={pi}
                      x={cx - bw / 2}
                      y={base}
                      width={bw}
                      height={Math.max(0, h - (pi > 0 ? 1 : 0))}
                      rx={pi === b.parts.length - 1 ? 2 : 0}
                      fill={`var(--series-${pi + 1})`}
                    />
                  ) : null;
                })}
              </g>
            );
          })}
          <text className="chart__tick" x={PAD.left} y={height - 4}>
            {bars[0].label}
          </text>
          <text className="chart__tick" x={W - PAD.right} y={height - 4} textAnchor="end">
            {bars[bars.length - 1].label}
          </text>
        </svg>
        {hover !== null && (
          <div className="chart__tip" style={{ left: `${((PAD.left + slot * hover + slot / 2) / W) * 100}%` }} role="status">
            <p className="label">{bars[hover].label}</p>
            {parts.map((p, pi) => (
              <p key={p}>
                <span className="legend__swatch" style={{ background: `var(--series-${pi + 1})` }} aria-hidden="true" />
                {p}: {format(bars[hover].parts[pi])}
              </p>
            ))}
            <p>Total: {format(totals[hover])}</p>
          </div>
        )}
      </div>
      <DataTable
        head={["Bar", ...parts, "Total"]}
        rows={bars.map((b, i) => [b.label, ...b.parts.map(format), format(totals[i])])}
      />
    </figure>
  );
}
