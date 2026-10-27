import { useState } from "react";

import { DIFFICULTIES, DIFFICULTY_LABEL, TONES, TONE_LABEL, usePart1Usage } from "../api/part1";
import { Kpi } from "../components/metrics";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

const WEEK_CHOICES = [4, 8, 12] as const;

function share(n: number, total: number): string {
  return total > 0 ? `${n} (${Math.round((n / total) * 100)}%)` : "0";
}

/** AD-3: plan page usage, and the tone (TN-1) and difficulty (IV-4) users pick, by week. */
export function PlanUsagePage() {
  const [weeks, setWeeks] = useState<number>(8);
  const usage = usePart1Usage(weeks);
  const data = usage.data;
  const total = data ? data.weeks.reduce((sum, w) => sum + w.sessions, 0) : 0;

  return (
    <>
      <PageHead title="Plan usage">
        <p>How the interview plan page is used, and the tone and difficulty of new sessions. Weeks start Monday, UTC.</p>
      </PageHead>
      <div className="segmented" role="group" aria-label="Weeks">
        {WEEK_CHOICES.map((n) => (
          <button key={n} type="button" className="btn btn--small" aria-pressed={weeks === n} onClick={() => setWeeks(n)}>
            {n} weeks
          </button>
        ))}
      </div>

      {usage.isPending && <Loading label="Loading plan usage" />}
      {usage.isError && <ErrorNotice error={usage.error} />}
      {data && (
        <>
          <section className="section" aria-labelledby="plan-page">
            <h2 id="plan-page">Plan page</h2>
            <div className="kpis">
              <Kpi label="Plan page views" metric={data.plan_page_views} />
              <Kpi label="Sessions started from the plan page" metric={data.plan_sessions} />
            </div>
          </section>

          <section className="section" aria-labelledby="mix-totals">
            <h2 id="mix-totals">Mix over {weeks} weeks</h2>
            <p className="muted">{total} sessions created.</p>
            <div className="kpis">
              {TONES.map((t) => (
                <div className="kpi" key={t}>
                  <p className="kpi__label">Tone: {TONE_LABEL[t]}</p>
                  <p className="kpi__value">{share(data.tone[t] ?? 0, total)}</p>
                </div>
              ))}
              {DIFFICULTIES.map((d) => (
                <div className="kpi" key={d}>
                  <p className="kpi__label">Difficulty: {DIFFICULTY_LABEL[d]}</p>
                  <p className="kpi__value">{share(data.difficulty[d] ?? 0, total)}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="section" aria-labelledby="mix-weeks">
            <h2 id="mix-weeks">By week</h2>
            <div className="table-wrap">
              <table aria-label="Tone and difficulty by week">
                <thead>
                  <tr>
                    <th scope="col">Week of</th>
                    <th scope="col">Sessions</th>
                    {TONES.map((t) => (
                      <th scope="col" key={t}>
                        {TONE_LABEL[t]}
                      </th>
                    ))}
                    {DIFFICULTIES.map((d) => (
                      <th scope="col" key={d}>
                        {DIFFICULTY_LABEL[d]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...data.weeks].reverse().map((w) => (
                    <tr key={w.week_start}>
                      <td>{w.week_start.slice(0, 10)}</td>
                      <td className="num">{w.sessions}</td>
                      {TONES.map((t) => (
                        <td className="num" key={t}>
                          {share(w.tone[t] ?? 0, w.sessions)}
                        </td>
                      ))}
                      {DIFFICULTIES.map((d) => (
                        <td className="num" key={d}>
                          {share(w.difficulty[d] ?? 0, w.sessions)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
