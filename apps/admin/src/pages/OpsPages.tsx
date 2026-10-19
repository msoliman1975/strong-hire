/** Operations section (OB-10..OB-14): Health, Performance, Errors, Jobs and Spend. */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  type ErrorStatusFilter,
  type LatencySeries,
  type OpsJob,
  type OpsTile,
  useOpsError,
  useOpsErrors,
  useOpsHealth,
  useOpsJobs,
  useOpsPerformance,
  useOpsSpend,
  useRetryJob,
  useUpdateError,
} from "../api/ops";
import { LineChart, Sparkline } from "../components/charts";
import { Kpi, ReasonButton, StatusBadge, formatValue } from "../components/metrics";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc, words } from "../format";
import { RangePicker, useRange } from "./OverviewPage";

function Tile({ tile }: { tile: OpsTile }) {
  return (
    <li className="tile" data-status={tile.status}>
      <div className="tile__head">
        <span className="label">{tile.label}</span>
        <StatusBadge status={tile.status} />
      </div>
      {tile.detail && <p className="kpi__note">{tile.detail}</p>}
      <p className="kpi__note">
        {tile.latency_ms !== null && tile.latency_ms !== undefined && `${Math.round(tile.latency_ms)} ms · `}
        {tile.version && `version ${tile.version} · `}
        checked {utc(tile.checked_at)}
      </p>
    </li>
  );
}

/** OB-10: is it up? */
export function OpsHealthPage() {
  const health = useOpsHealth();
  const data = health.data;
  return (
    <>
      <PageHead title="Health">
        <p>Services from their heartbeats, dependencies from the sampler probes. Refreshes every 30 seconds.</p>
      </PageHead>
      {health.isPending && <Loading label="Loading health" />}
      {health.isError && <ErrorNotice error={health.error} />}
      {data && (
        <>
          {data.redis_error && (
            <div className="notice notice--error" role="alert">
              <p>Heartbeats could not be read ({data.redis_error}). Service tiles use the last samples.</p>
            </div>
          )}
          <section className="section" aria-labelledby="services">
            <h2 id="services">Services</h2>
            <ul className="tiles">
              {data.tiles
                .filter((t) => t.kind === "service")
                .map((t) => (
                  <Tile key={t.key} tile={t} />
                ))}
            </ul>
          </section>
          <section className="section" aria-labelledby="deps">
            <h2 id="deps">Dependencies</h2>
            <ul className="tiles">
              {data.tiles
                .filter((t) => t.kind === "dependency")
                .map((t) => (
                  <Tile key={t.key} tile={t} />
                ))}
            </ul>
          </section>
          <section className="section" aria-labelledby="host">
            <h2 id="host">Host, last 24 hours</h2>
            {data.host.length === 0 ? (
              <p className="muted">No host samples yet. The sampler (OB-5) writes them every minute.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Metric</th>
                      <th scope="col" className="num">
                        Now
                      </th>
                      <th scope="col">24 hours</th>
                      <th scope="col">Sampled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.host.map((h) => (
                      <tr key={`${h.metric}-${h.label}`}>
                        <td>{h.label}</td>
                        <td className="num">{formatValue(h.unit === "pct" && h.latest !== null ? h.latest / 100 : h.latest, h.unit)}</td>
                        <td>
                          <Sparkline values={h.points.map((p) => p.value)} label={`${h.label}, last 24 hours`} />
                        </td>
                        <td>{utc(h.latest_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function latencyLines(series: LatencySeries[], which: "p50_ms" | "p95_ms") {
  return series.map((s) => ({
    key: s.key,
    label: words(s.key),
    points: s.points.map((p) => ({ t: p.t, v: p[which] ?? null })),
  }));
}

/** OB-11: is it fast? */
export function OpsPerformancePage() {
  const [range, setRange] = useRange("24h");
  const perf = useOpsPerformance(range);
  const data = perf.data;
  const ms = (v: number) => `${Math.round(v)} ms`;
  return (
    <>
      <PageHead title="Performance">
        <p>Voice latency per turn (OB-3) and interviewer model latency. Targets: p50 800 ms, p95 1.5 s.</p>
      </PageHead>
      <RangePicker value={range} onChange={setRange} />
      {perf.isPending && <Loading label="Loading performance" />}
      {perf.isError && <ErrorNotice error={perf.error} />}
      {data && (
        <>
          <section className="section" aria-labelledby="voice">
            <h2 id="voice">Voice latency by component</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Component</th>
                    <th scope="col" className="num">
                      Turns
                    </th>
                    <th scope="col" className="num">
                      p50
                    </th>
                    <th scope="col" className="num">
                      p95
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.voice.map((v) => (
                    <tr key={v.key}>
                      <td>{words(v.key)}</td>
                      <td className="num">{v.n}</td>
                      <td className="num">{formatValue(v.p50_ms, "ms")}</td>
                      <td className="num">{formatValue(v.p95_ms, "ms")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel">
              <LineChart
                title="End-to-end p50 and p95"
                format={ms}
                target={{ value: 1500, label: "p95 target" }}
                series={[
                  ...latencyLines(data.voice_series.filter((s) => s.key === "e2e"), "p50_ms").map((s) => ({ ...s, key: "p50", label: "p50" })),
                  ...latencyLines(data.voice_series.filter((s) => s.key === "e2e"), "p95_ms").map((s) => ({ ...s, key: "p95", label: "p95" })),
                ]}
              />
            </div>
            <div className="panel">
              <LineChart
                title="p95 by component"
                format={ms}
                series={latencyLines(
                  data.voice_series.filter((s) => s.key !== "e2e" && s.points.length > 0).slice(0, 3),
                  "p95_ms",
                )}
              />
              <p className="kpi__note">The three components with data are shown; the table above has all of them.</p>
            </div>
          </section>
          <section className="section" aria-labelledby="llm">
            <h2 id="llm">Model latency ({data.llm_role})</h2>
            {data.llm.length === 0 ? (
              <p className="muted">No traced model calls in this range.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Call</th>
                      <th scope="col" className="num">
                        Calls
                      </th>
                      <th scope="col" className="num">
                        p50
                      </th>
                      <th scope="col" className="num">
                        p95
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.llm.map((v) => (
                      <tr key={v.key}>
                        <td>{words(v.key)}</td>
                        <td className="num">{v.n}</td>
                        <td className="num">{formatValue(v.p50_ms, "ms")}</td>
                        <td className="num">{formatValue(v.p95_ms, "ms")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="kpis">
              <Kpi label="Other roles" metric={data.llm_other_roles} />
              <Kpi label="Queue wait" metric={data.queue_wait} />
            </div>
          </section>
        </>
      )}
    </>
  );
}

function ErrorDetail({ id }: { id: string }) {
  const detail = useOpsError(id);
  const update = useUpdateError();
  if (detail.isPending) return <Loading label="Loading the error" />;
  if (detail.isError) return <ErrorNotice error={detail.error} />;
  const { group, sample_stack, daily, events } = detail.data;
  const resolved = group.status === "resolved";
  return (
    <div className="panel error-detail">
      <div className="row">
        <Sparkline values={daily} label="Events per day, last 14 days" width={200} />
        <span className="muted">last 14 days</span>
        <ReasonButton
          label={resolved ? "Reopen" : "Mark resolved"}
          confirm={resolved ? `Reopen ${group.exception_type}` : `Resolve ${group.exception_type}`}
          pending={update.isPending}
          error={update.error}
          onSubmit={(reason) => update.mutateAsync({ id: group.id, status: resolved ? "open" : "resolved", reason })}
        />
      </div>
      {resolved && (
        <p className="muted">
          Resolved by {group.resolved_by ?? "-"} at {utc(group.resolved_at)}. It reopens if it happens again.
        </p>
      )}
      <h3>Sample stack</h3>
      <pre className="details-json">{sample_stack ?? "No stack saved."}</pre>
      <h3>Recent events</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">At</th>
              <th scope="col">Service</th>
              <th scope="col">Release</th>
              <th scope="col">Request</th>
              <th scope="col">Interview</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                <td>{utc(e.at)}</td>
                <td>{e.service}</td>
                <td>{e.release ?? "-"}</td>
                <td>{e.request_id ?? "-"}</td>
                <td>{e.session_id ? <Link to={`/interviews/${e.session_id}`}>Open</Link> : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** OB-12: what broke? */
export function OpsErrorsPage() {
  const [params, setParams] = useSearchParams();
  const status = (["open", "resolved", "all"].includes(params.get("status") ?? "") ? params.get("status") : "open") as ErrorStatusFilter;
  const [openId, setOpenId] = useState<string | null>(params.get("group"));
  const errors = useOpsErrors(status);
  return (
    <>
      <PageHead title="Errors">
        <p>Unhandled exceptions and error logs from api, worker and voice, grouped by fingerprint (OB-4).</p>
      </PageHead>
      <div className="segmented" role="group" aria-label="Status">
        {(["open", "resolved", "all"] as const).map((s) => (
          <button
            key={s}
            type="button"
            className="btn btn--small"
            aria-pressed={status === s}
            onClick={() => setParams(new URLSearchParams({ status: s }), { replace: true })}
          >
            {words(s)}
          </button>
        ))}
      </div>
      {errors.isPending && <Loading label="Loading errors" />}
      {errors.isError && <ErrorNotice error={errors.error} />}
      {errors.data && errors.data.length === 0 && <p className="section">No {status === "all" ? "" : status} error groups.</p>}
      {errors.data && errors.data.length > 0 && (
        <ul className="error-list section">
          {errors.data.map((g) => (
            <li key={g.id} className="panel">
              <div className="error-row">
                <div>
                  <button type="button" className="btn--link" aria-expanded={openId === g.id} onClick={() => setOpenId(openId === g.id ? null : g.id)}>
                    {g.exception_type}
                  </button>
                  <span className="tag"> {g.service}</span>
                  {g.status === "resolved" && <span className="muted"> (resolved)</span>}
                  <p className="error-msg">{g.message}</p>
                  <p className="kpi__note">
                    {g.count} total, {g.events_24h} in 24 h · last {utc(g.last_seen)} · first {utc(g.first_seen)}
                    {g.release && ` · ${g.release}`}
                  </p>
                </div>
                <Sparkline values={g.sparkline} label={`${g.exception_type}, events per hour over 24 hours`} />
              </div>
              {openId === g.id && <ErrorDetail id={g.id} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function JobTable({ title, jobs }: { title: string; jobs: OpsJob[] }) {
  const retry = useRetryJob();
  return (
    <section className="section" aria-label={title}>
      <h2>{title}</h2>
      {jobs.length === 0 ? (
        <p className="muted">None failed in the last 7 days or stuck now.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Created</th>
                <th scope="col">User</th>
                <th scope="col">State</th>
                <th scope="col">Reason</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.kind === "scoring" ? <Link to={`/interviews/${j.id}`}>{utc(j.created_at)}</Link> : utc(j.created_at)}</td>
                  <td>{j.user_email ?? "-"}</td>
                  <td>
                    {j.state} <span className="muted">({words(j.status)})</span>
                  </td>
                  <td>{j.reason ?? "-"}</td>
                  <td>
                    {j.retryable ? (
                      <ReasonButton
                        label="Retry"
                        confirm={`Retry ${words(j.kind)} for ${j.user_email ?? j.id}`}
                        pending={retry.isPending}
                        error={retry.variables?.id === j.id ? retry.error : undefined}
                        onSubmit={(reason) => retry.mutateAsync({ kind: j.kind, id: j.id, reason })}
                      />
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** OB-13: failed or stuck background work, with Retry (audited). */
export function OpsJobsPage() {
  const jobs = useOpsJobs();
  const data = jobs.data;
  return (
    <>
      <PageHead title="Jobs">
        <p>From the domain status columns (Arq results are not kept). Retry re-enqueues the same job.</p>
      </PageHead>
      {jobs.isPending && <Loading label="Loading jobs" />}
      {jobs.isError && <ErrorNotice error={jobs.error} />}
      {data && (
        <>
          {data.jobs_paused.length > 0 && (
            <div className="notice" role="status">
              <p>Paused job types (OC-5): {data.jobs_paused.map(words).join(", ")}. Retried jobs wait in the queue.</p>
            </div>
          )}
          <div className="kpis">
            <Kpi label="Queue depth" metric={data.queue_depth} />
          </div>
          {data.queue_series.length > 0 && (
            <div className="panel">
              <LineChart
                title="Queue depth, last 24 hours"
                format={(v) => v.toFixed(0)}
                series={data.queue_series.map((s) => ({
                  key: JSON.stringify(s.labels),
                  label: Object.values(s.labels).join(", ") || "queue",
                  points: s.points.map((p) => ({ t: p.t, v: p.value })),
                }))}
              />
            </div>
          )}
          <JobTable title="Gap analyses" jobs={data.gap_analyses} />
          <JobTable title="Scorings" jobs={data.scorings} />
        </>
      )}
    </>
  );
}

/** OB-14: what does it cost? */
export function OpsSpendPage() {
  const spend = useOpsSpend();
  const data = spend.data;
  return (
    <>
      <PageHead title="Spend">
        <p>Model cost from usage rows (UTC days), against the daily cap (OC-3).</p>
      </PageHead>
      {spend.isPending && <Loading label="Loading spend" />}
      {spend.isError && <ErrorNotice error={spend.error} />}
      {data && (
        <>
          <div className="kpis">
            <Kpi label="Today" metric={{ measured: true, value: data.today_usd, unit: "usd", note: `Cap $${data.daily_cap_usd.toFixed(2)}` }} />
            <Kpi label="Today vs cap" metric={{ measured: true, value: data.cap_pct, unit: "pct", target: 0.8, note: "The Spend high alert fires at 80%" }} />
            <Kpi label="This month" metric={{ measured: true, value: data.month_usd, unit: "usd" }} />
          </div>
          <div className="meter" role="meter" aria-label="Today's cost against the cap" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((data.cap_pct ?? 0) * 100)}>
            <span style={{ width: `${Math.min(100, (data.cap_pct ?? 0) * 100)}%` }} data-level={(data.cap_pct ?? 0) >= 1 ? "critical" : (data.cap_pct ?? 0) >= 0.8 ? "warning" : undefined} />
          </div>
          <div className="panel section">
            <LineChart
              title="Cost per day this month"
              format={(v) => `$${v.toFixed(2)}`}
              series={[{ key: "cost", label: "Cost", points: data.daily.map((p) => ({ t: p.t, v: p.value })) }]}
              target={{ value: data.daily_cap_usd, label: "daily cap" }}
            />
          </div>
          <div className="split section">
            {[
              ["By component", data.by_component],
              ["By role", data.by_role],
            ].map(([title, rows]) => (
              <div className="panel" key={title as string}>
                <h3>{title as string}</h3>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col" className="num">
                        Today
                      </th>
                      <th scope="col" className="num">
                        Month
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(rows as typeof data.by_role).map((r) => (
                      <tr key={r.key}>
                        <td>{words(r.key)}</td>
                        <td className="num">${r.today_usd.toFixed(4)}</td>
                        <td className="num">${r.month_usd.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
          <section className="section" aria-labelledby="litellm">
            <h2 id="litellm">LiteLLM budgets ({data.litellm.profile})</h2>
            {data.litellm.tracked ? (
              <dl className="dl panel">
                <dt>Key today</dt>
                <dd>
                  ${data.litellm.today?.spend_usd.toFixed(4)} of {data.litellm.today?.budget_usd ? `$${data.litellm.today.budget_usd}` : "no budget"}
                </dd>
                <dt>Team this month</dt>
                <dd>
                  {data.litellm.month
                    ? `$${data.litellm.month.spend_usd.toFixed(4)} of ${data.litellm.month.budget_usd ? `$${data.litellm.month.budget_usd}` : "no budget"}`
                    : "-"}
                </dd>
                <dt>Rate limit</dt>
                <dd>{data.litellm.rpm_limit ? `${data.litellm.rpm_limit} requests a minute` : "-"}</dd>
              </dl>
            ) : (
              <p className="muted">Not tracked: this profile has no LiteLLM app key, or LiteLLM did not answer.</p>
            )}
          </section>
          <section className="section" aria-labelledby="hosted">
            <h2 id="hosted">Hosted equivalent of self-hosted speech (D-12)</h2>
            <p className="muted">What this month's self-hosted speech would cost at hosted prices. Not part of session cost.</p>
            <dl className="dl panel">
              <dt>Speech to text</dt>
              <dd>
                {Math.round(data.hosted_equivalent.stt_seconds / 60)} min
                {data.hosted_equivalent.stt_usd !== null && data.hosted_equivalent.stt_usd !== undefined && `, $${data.hosted_equivalent.stt_usd.toFixed(2)}`}
              </dd>
              <dt>Text to speech</dt>
              <dd>
                {Math.round(data.hosted_equivalent.tts_characters).toLocaleString("en-US")} characters
                {data.hosted_equivalent.tts_usd !== null && data.hosted_equivalent.tts_usd !== undefined && `, $${data.hosted_equivalent.tts_usd.toFixed(2)}`}
              </dd>
              <dt>Total</dt>
              <dd>
                {data.hosted_equivalent.configured
                  ? `$${(data.hosted_equivalent.total_usd ?? 0).toFixed(2)}`
                  : data.hosted_equivalent.reason}
              </dd>
            </dl>
          </section>
        </>
      )}
    </>
  );
}
