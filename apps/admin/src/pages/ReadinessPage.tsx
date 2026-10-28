import { usePart3Readiness } from "../api/part3";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { sentence } from "../format";

/**
 * AD-5, RD-1: practice readiness by skill across users. Aggregate only, and labeled a practice
 * estimate (RD-3), never a prediction.
 */
export function ReadinessPage() {
  const readiness = usePart3Readiness();
  const data = readiness.data;

  return (
    <>
      <PageHead title="Readiness">
        <p>How ready practice shows candidates to be, per skill, across all users.</p>
      </PageHead>
      {readiness.isPending && <Loading label="Loading readiness" />}
      {readiness.isError && <ErrorNotice error={readiness.error} />}
      {data && (
        <>
          <div className="notice section" role="note">
            <p>
              <strong>Practice estimate.</strong> {data.note}
            </p>
          </div>
          <p className="muted">
            {data.users} users with Realistic scores in the last {data.window_days} days.
          </p>
          {data.skills.length === 0 ? (
            <p>No Realistic session was scored in the window.</p>
          ) : (
            <div className="table-wrap">
              <table aria-label="Readiness by skill">
                <thead>
                  <tr>
                    <th scope="col">Skill</th>
                    <th scope="col">Users</th>
                    <th scope="col">Enough data</th>
                    <th scope="col">At the bar (3+)</th>
                    <th scope="col">Mean score</th>
                    <th scope="col">Sessions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.skills.map((s) => (
                    <tr key={s.competency}>
                      <td>{sentence(s.competency)}</td>
                      <td className="num">{s.users}</td>
                      <td className="num">{s.users_enough_data}</td>
                      <td className="num">{s.users_at_bar}</td>
                      <td className="num">{s.mean_score === null ? "Not enough data" : s.mean_score.toFixed(2)}</td>
                      <td className="num">{s.sessions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
