import { Link } from "react-router";

import { useAdminUsers } from "../../api/admin";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { utc } from "./format";

export function AdminUsersPage() {
  const users = useAdminUsers();
  return (
    <>
      <PageHead title="Users">
        <p>Everyone who has signed up, newest first.</p>
      </PageHead>
      {users.isPending && <Loading label="Loading users" />}
      {users.isError && <ErrorNotice error={users.error} />}
      {users.data && users.data.length === 0 && <p>No users yet.</p>}
      {users.data && users.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Signed up</th>
                <th scope="col">Last sign-in</th>
                <th scope="col">Plan</th>
                <th scope="col" className="num">
                  Minutes used
                </th>
                <th scope="col">Consent</th>
                <th scope="col" className="num">
                  Interviews
                </th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    <Link to={`/admin/interviews?user=${u.id}`}>{u.email}</Link>
                    {u.is_admin && <span className="tag"> Admin</span>}
                  </td>
                  <td>{utc(u.created_at)}</td>
                  <td>{utc(u.last_sign_in_at)}</td>
                  <td>
                    {u.plan === "paid" ? "Paid" : "Free"}
                    {u.subscription_status ? ` (${u.subscription_status})` : ""}
                  </td>
                  <td className="num">{u.plan === "paid" ? `${u.minutes_used} of ${u.minutes_cap}` : "-"}</td>
                  <td>{u.training_consent ? "Yes" : "No"}</td>
                  <td className="num">{u.interviews}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
