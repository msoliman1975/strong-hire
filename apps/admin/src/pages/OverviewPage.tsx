import { useSearchParams } from "react-router";

import { RANGES, type AdminMetric, type RangeKey, useOverview } from "../api/ops";
import { StackedBars } from "../components/charts";
import { Kpi, formatValue } from "../components/metrics";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { words } from "../format";

export function RangePicker({ value, onChange, label = "Range" }: { value: RangeKey; onChange: (r: RangeKey) => void; label?: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {RANGES.map((r) => (
        <button
          key={r.key}
          type="button"
          className="btn btn--small"
          aria-pressed={value === r.key}
          onClick={() => onChange(r.key)}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

export function useRange(fallback: RangeKey = "7d"): [RangeKey, (r: RangeKey) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("range");
  const range = RANGES.some((r) => r.key === raw) ? (raw as RangeKey) : fallback;
  return [
    range,
    (r) => {
      const next = new URLSearchParams(params);
      next.set("range", r);
      setParams(next, { replace: true });
    },
  ];
}

function Tiles({ items }: { items: [string, AdminMetric][] }) {
  return (
    <div className="kpis">
      {items.map(([label, metric]) => (
        <Kpi key={label} label={label} metric={metric} />
      ))}
    </div>
  );
}

/** AD-2: funnel, revenue, usage, cost and quality, each against the previous period (AO-1). */
export function OverviewPage() {
  const [range, setRange] = useRange();
  const overview = useOverview(range);
  const data = overview.data;

  return (
    <>
      <PageHead title="Overview">
        <p>Each number is compared with the previous period of the same length. Times are UTC.</p>
      </PageHead>
      <RangePicker value={range} onChange={setRange} />

      {overview.isPending && <Loading label="Loading the overview" />}
      {overview.isError && <ErrorNotice error={overview.error} />}
      {data && (
        <>
          <section className="section" aria-labelledby="funnel">
            <h2 id="funnel">Funnel</h2>
            <p className="muted">Users who signed up in the range, and how far they got.</p>
            <ol className="funnel">
              {data.funnel.map((step) => {
                const top = data.funnel[0].metric.value || 0;
                const value = step.metric.value ?? 0;
                const width = top > 0 ? Math.max(2, (value / top) * 100) : 0;
                return (
                  <li key={step.key}>
                    <div className="funnel__head">
                      <span className="label">{step.label}</span>
                      <span className="num">
                        {formatValue(step.metric.value, "count")}
                        <span className="muted"> (previous {formatValue(step.metric.previous, "count")})</span>
                      </span>
                    </div>
                    <div className="funnel__bar" aria-hidden="true">
                      <span style={{ width: `${width}%` }} />
                    </div>
                    {step.conversion && (
                      <p className="kpi__note">
                        {formatValue(step.conversion.value, "pct")} of the step before
                        {step.conversion.previous !== null && step.conversion.previous !== undefined &&
                          ` (previous ${formatValue(step.conversion.previous, "pct")})`}
                        {step.conversion.target !== null && step.conversion.target !== undefined &&
                          `, target ${formatValue(step.conversion.target, "pct")}`}
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="section" aria-labelledby="revenue">
            <h2 id="revenue">Revenue</h2>
            <Tiles
              items={[
                ["Active paid subscribers", data.revenue.active_subscribers],
                ["MRR", data.revenue.mrr_usd],
                ["New subscriptions", data.revenue.new_subscriptions],
                ["Cancellations", data.revenue.cancellations],
                ["Monthly churn", data.revenue.monthly_churn],
                ["Refunds", data.revenue.refunds],
              ]}
            />
          </section>

          <section className="section" aria-labelledby="usage">
            <h2 id="usage">Usage</h2>
            <Tiles
              items={[
                ["Sessions started", data.usage.sessions_started],
                ["Sessions completed", data.usage.sessions_completed],
                ["Sessions failed", data.usage.sessions_failed],
                ["Minutes billed", data.usage.minutes],
                ["Sessions per paid user", data.usage.sessions_per_paid_user],
                ["Voice sessions", data.usage.voice_sessions],
                ["Text sessions", data.usage.text_sessions],
              ]}
            />
          </section>

          <section className="section" aria-labelledby="cost">
            <h2 id="cost">Cost</h2>
            <Tiles
              items={[
                ["Model cost", data.cost.total_usd],
                ["Model cost per completed session", data.cost.per_completed_session_usd],
                ["Server share per session", data.cost.server_share_per_session_usd],
                ["Rows without a price", data.cost.unmetered_rows],
              ]}
            />
            <div className="panel">
              <StackedBars
                title="Model cost per day (UTC) by component"
                parts={["llm", "stt", "tts"]}
                format={(v) => `$${v.toFixed(2)}`}
                bars={data.cost.by_day.map((d) => ({
                  label: d.day.slice(0, 10),
                  parts: [d.llm_usd, d.stt_usd, d.tts_usd],
                }))}
              />
            </div>
            <div className="split">
              <SliceTable title="By component" rows={data.cost.by_component} />
              <SliceTable title="By role" rows={data.cost.by_role} />
            </div>
          </section>

          <section className="section" aria-labelledby="quality">
            <h2 id="quality">Quality</h2>
            <Tiles
              items={[
                ["Session failure rate", data.quality.failure_rate],
                ["Voice latency p50", data.quality.voice_p50_ms],
                ["Voice latency p95", data.quality.voice_p95_ms],
                ["Realism rating", data.quality.realism_rating],
                ["Scorer agreement", data.quality.scorer_agreement],
                ["Offer reported", data.quality.offer_reported],
              ]}
            />
          </section>
        </>
      )}
    </>
  );
}

function SliceTable({ title, rows }: { title: string; rows: { key: string; cost_usd: number; rows: number }[] }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="muted">No usage in this range.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col" className="num">
                Rows
              </th>
              <th scope="col" className="num">
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{words(r.key)}</td>
                <td className="num">{r.rows}</td>
                <td className="num">${r.cost_usd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
