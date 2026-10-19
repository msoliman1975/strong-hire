import { useMySessions, useRevokeSession } from "../api/settings";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

/**
 * Settings > My sessions (AA-8): where I am signed in to the admin app. A session ends 2 hours
 * after it was last used, and 12 hours after sign-in at the latest (AA-3).
 */
export function MySessionsPage() {
  const sessions = useMySessions();
  const revoke = useRevokeSession();
  return (
    <>
      <PageHead title="My sessions">
        <p>Where you are signed in. A session ends after 2 hours without use, and 12 hours after sign-in at the latest.</p>
      </PageHead>
      {revoke.isError && <ErrorNotice error={revoke.error} />}
      {sessions.isPending && <Loading label="Loading sessions" />}
      {sessions.isError && <ErrorNotice error={sessions.error} />}
      {sessions.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Signed in</th>
                <th scope="col">Last used</th>
                <th scope="col">Ends</th>
                <th scope="col">IP address</th>
                <th scope="col">Browser</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.data.map((s) => (
                <tr key={s.id}>
                  <td>
                    {utc(s.created_at)}
                    {s.current && <span className="tag"> This browser</span>}
                  </td>
                  <td>{utc(s.last_seen_at)}</td>
                  <td>{utc(s.ends_at)}</td>
                  <td>{s.ip ?? "-"}</td>
                  <td className="muted">{s.user_agent ?? "-"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--small"
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate({ id: s.id, current: s.current })}
                    >
                      {s.current ? "Sign out here" : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
