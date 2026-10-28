import { useState } from "react";

import { type CoachEvalRun, type Part3Coach, usePart3Coach } from "../api/part3";
import { Kpi } from "../components/metrics";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

const WEEK_CHOICES = [4, 8, 12] as const;

function verdict(passed: boolean | null | undefined): string {
  if (passed === true) return "Pass";
  if (passed === false) return "Fail";
  return "Info";
}

function EvalRun({ run }: { run: CoachEvalRun }) {
  return (
    <>
      <p>
        {verdict(run.passed)} on the <strong>{run.profile}</strong> profile, {utc(run.started_at)}, commit{" "}
        <code>{run.git_sha.slice(0, 7)}</code> ({run.file}).
        {run.dev_data && " Development data: not a launch result."}
      </p>
      <div className="table-wrap">
        <table aria-label="Coach eval metrics">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Value</th>
              <th scope="col">Threshold</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {run.metrics.map((m) => (
              <tr key={m.key}>
                <td>{m.name}</td>
                <td className="num">{m.value === null ? "–" : String(Math.round(m.value * 1000) / 1000)}</td>
                <td>{m.threshold}</td>
                <td>{verdict(m.passed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Evals({ evals }: { evals: Part3Coach["evals"] }) {
  return (
    <section className="section" aria-labelledby="coach-evals">
      <h2 id="coach-evals">Coach evals</h2>
      <p className="muted">
        The eval harness checks that the coach never adds facts the candidate did not say (CO-9). Read from the newest
        report in evals/reports; a hosted run is shown before a newer development run.
      </p>
      {evals.latest ? <EvalRun run={evals.latest} /> : <p>{evals.reason ?? "No coach eval run yet."}</p>}
      {evals.runs.length > 1 && (
        <ul aria-label="Recent coach eval runs">
          {evals.runs.map((r) => (
            <li key={r.file}>
              {utc(r.started_at)}: {r.profile}, {verdict(r.passed)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * AD-5: the AI coach. Sessions and minutes per week, minutes against plan caps, cost per coach
 * session, and the latest coach eval results. Counts only: the API never sends what was said.
 */
export function CoachPage() {
  const [weeks, setWeeks] = useState<number>(8);
  const coach = usePart3Coach(weeks);
  const data = coach.data;

  return (
    <>
      <PageHead title="Coach">
        <p>
          Coach sessions, their minutes and cost, and the coach evals. Aggregate only: coach conversations are never
          shown here. Weeks start Monday, UTC.
        </p>
      </PageHead>
      <div className="segmented" role="group" aria-label="Weeks">
        {WEEK_CHOICES.map((n) => (
          <button key={n} type="button" className="btn btn--small" aria-pressed={weeks === n} onClick={() => setWeeks(n)}>
            {n} weeks
          </button>
        ))}
      </div>

      {coach.isPending && <Loading label="Loading coach metrics" />}
      {coach.isError && <ErrorNotice error={coach.error} />}
      {data && (
        <>
          <section className="section" aria-labelledby="coach-kpis">
            <h2 id="coach-kpis">Sessions and cost</h2>
            <div className="kpis">
              <div className="kpi">
                <p className="kpi__label">Coach sessions</p>
                <p className="kpi__value">{data.sessions}</p>
                <p className="kpi__note">
                  {data.users} users, {data.minutes} minutes
                </p>
              </div>
              <Kpi label="Minutes per session" metric={data.minutes_per_session} />
              <Kpi label="Cost per coach session" metric={data.cost_per_session} />
            </div>
            <p className="muted">
              Gentle {data.by_style.gentle ?? 0}, direct {data.by_style.direct ?? 0}. Voice {data.by_channel.voice ?? 0},
              text {data.by_channel.text ?? 0}. Total cost ${data.cost_total_usd.toFixed(2)}.
            </p>
          </section>

          <section className="section" aria-labelledby="coach-caps">
            <h2 id="coach-caps">Minutes against plan caps</h2>
            <p className="muted">Coach minutes do not use plan minutes today; pricing for coach time is undecided.</p>
            <div className="kpis">
              <Kpi label="Coach minutes as a share of plan caps" metric={data.cap_share} />
            </div>
            <dl className="dl panel">
              <dt>Users on a paid plan</dt>
              <dd>{data.caps.paid_users}</dd>
              <dt>Their coach minutes this period</dt>
              <dd>{data.caps.coach_minutes}</dd>
              <dt>Their interview minutes used</dt>
              <dd>
                {data.caps.interview_minutes} of {data.caps.cap_minutes}
              </dd>
              <dt>Would pass the cap if coach minutes counted</dt>
              <dd>{data.caps.over_cap_if_counted}</dd>
              <dt>Coach minutes of free users</dt>
              <dd>{data.caps.free_user_coach_minutes}</dd>
            </dl>
          </section>

          <section className="section" aria-labelledby="coach-weeks">
            <h2 id="coach-weeks">By week</h2>
            <div className="table-wrap">
              <table aria-label="Coach sessions by week">
                <thead>
                  <tr>
                    <th scope="col">Week of</th>
                    <th scope="col">Sessions</th>
                    <th scope="col">Minutes</th>
                    <th scope="col">Voice</th>
                    <th scope="col">Text</th>
                    <th scope="col">Users</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.weeks].reverse().map((w) => (
                    <tr key={w.week_start}>
                      <td>{w.week_start.slice(0, 10)}</td>
                      <td className="num">{w.sessions}</td>
                      <td className="num">{w.minutes}</td>
                      <td className="num">{w.voice}</td>
                      <td className="num">{w.text}</td>
                      <td className="num">{w.users}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <Evals evals={data.evals} />
        </>
      )}
    </>
  );
}
