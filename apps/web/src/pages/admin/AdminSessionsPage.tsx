import { Link, useSearchParams } from "react-router";

import { type AdminSessionFilters, useAdminSessions, useAdminUsers } from "../../api/admin";
import type { InterviewType } from "../../api/types";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { difficultyLabel, interviewTypeLabel, modeLabel } from "../../labels";
import { clock, money, utc, words } from "./format";

const TYPES = Object.keys(interviewTypeLabel) as InterviewType[];

/** Interviews of all users (R2), with filters in the URL so a view can be shared. */
export function AdminSessionsPage() {
  const [params, setParams] = useSearchParams();
  const filters: AdminSessionFilters = {
    user_id: params.get("user") || undefined,
    day_from: params.get("from") || undefined,
    day_to: params.get("to") || undefined,
    interview_type: (params.get("type") as InterviewType | null) || undefined,
  };
  const users = useAdminUsers();
  const sessions = useAdminSessions(filters);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHead title="Interviews">
        <p>All users, newest first. Cost is the interviewer model cost.</p>
      </PageHead>

      <form className="panel filters" aria-label="Filters" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="f-user">User</label>
          <select id="f-user" value={filters.user_id ?? ""} onChange={(e) => setFilter("user", e.target.value)}>
            <option value="">All users</option>
            {users.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.email}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-from">From</label>
          <input id="f-from" type="date" value={filters.day_from ?? ""} onChange={(e) => setFilter("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="f-to">To</label>
          <input id="f-to" type="date" value={filters.day_to ?? ""} onChange={(e) => setFilter("to", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="f-type">Type</label>
          <select
            id="f-type"
            value={filters.interview_type ?? ""}
            onChange={(e) => setFilter("type", e.target.value)}
          >
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {interviewTypeLabel[t]}
              </option>
            ))}
          </select>
        </div>
      </form>

      {sessions.isPending && <Loading label="Loading interviews" />}
      {sessions.isError && <ErrorNotice error={sessions.error} />}
      {sessions.data && (
        <>
          <section className="section" aria-labelledby="daily-cost">
            <h2 id="daily-cost">Cost per day</h2>
            {sessions.data.daily.length === 0 ? (
              <p>No interviews match these filters.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Day (UTC)</th>
                      <th scope="col" className="num">
                        Interviews
                      </th>
                      <th scope="col" className="num">
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.data.daily.map((d) => (
                      <tr key={d.day}>
                        <td>{d.day}</td>
                        <td className="num">{d.sessions}</td>
                        <td className="num">{money(d.cost_usd)}</td>
                      </tr>
                    ))}
                    <tr>
                      <th scope="row">Total</th>
                      <td className="num">{sessions.data.sessions.length}</td>
                      <td className="num">{money(sessions.data.total_cost_usd)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {sessions.data.sessions.length > 0 && (
            <section className="section" aria-labelledby="interview-list">
              <h2 id="interview-list">Interviews</h2>
              {sessions.data.sessions.length >= sessions.data.limit && (
                <p className="muted">Showing the newest {sessions.data.limit}. Use the filters to see older ones.</p>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">User</th>
                      <th scope="col">Type</th>
                      <th scope="col">Setup</th>
                      <th scope="col" className="num">
                        Length
                      </th>
                      <th scope="col">Status</th>
                      <th scope="col">Signal</th>
                      <th scope="col" className="num">
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.data.sessions.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <Link to={`/admin/interviews/${s.id}`}>{utc(s.created_at)}</Link>
                        </td>
                        <td>
                          {s.user_email ?? "-"}
                          {!s.training_consent && <span className="muted"> (no consent)</span>}
                        </td>
                        <td>{interviewTypeLabel[s.interview_type]}</td>
                        <td>
                          {difficultyLabel[s.difficulty]}, {modeLabel[s.mode]}, {s.channel}
                        </td>
                        <td className="num">
                          {s.duration_s === null ? "-" : clock(s.duration_s * 1000)} of {s.duration_min} min
                        </td>
                        <td>{words(s.status)}</td>
                        <td>{s.hire_signal ?? "-"}</td>
                        <td className="num">{money(s.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}
