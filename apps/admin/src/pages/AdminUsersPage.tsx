import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { type UserFilters, useUserList } from "../api/users";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

const PAGE_SIZE = 50;
const FILTER_KEYS = [
  "q",
  "plan",
  "status",
  "signed_up_from",
  "signed_up_to",
  "last_sign_in_from",
  "last_sign_in_to",
] as const;

function filtersFrom(params: URLSearchParams): UserFilters {
  const out: Record<string, string | number> = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) out[key] = value;
  }
  const page = Number(params.get("page") ?? "1");
  out.page = Number.isInteger(page) && page > 0 ? page : 1;
  out.page_size = PAGE_SIZE;
  return out as UserFilters;
}

/** AU-1: search by email, name or id; filter by plan, status, sign-up and last sign-in. */
export function AdminUsersPage() {
  const [params, setParams] = useSearchParams();
  const filters = filtersFrom(params);
  const users = useUserList(filters);
  const [q, setQ] = useState(filters.q ?? "");

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const page = filters.page ?? 1;
  const total = users.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHead title="Users">
        <p>Search by email, name or user id. Newest sign-ups first.</p>
      </PageHead>

      <form
        className="panel filters"
        aria-label="Filters"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilter("q", q.trim());
        }}
      >
        <div className="field">
          <label htmlFor="u-q">Search</label>
          <input id="u-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Email, name or id" />
        </div>
        <div className="field">
          <label htmlFor="u-plan">Plan</label>
          <select id="u-plan" value={filters.plan ?? ""} onChange={(e) => setFilter("plan", e.target.value)}>
            <option value="">Any plan</option>
            <option value="free">Free</option>
            <option value="paid">Paid or comp</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="u-status">Status</label>
          <select id="u-status" value={filters.status ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="u-su-from">Signed up from</label>
          <input
            id="u-su-from"
            type="date"
            value={filters.signed_up_from ?? ""}
            onChange={(e) => setFilter("signed_up_from", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="u-su-to">Signed up to</label>
          <input
            id="u-su-to"
            type="date"
            value={filters.signed_up_to ?? ""}
            onChange={(e) => setFilter("signed_up_to", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="u-ls-from">Last sign-in from</label>
          <input
            id="u-ls-from"
            type="date"
            value={filters.last_sign_in_from ?? ""}
            onChange={(e) => setFilter("last_sign_in_from", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="u-ls-to">Last sign-in to</label>
          <input
            id="u-ls-to"
            type="date"
            value={filters.last_sign_in_to ?? ""}
            onChange={(e) => setFilter("last_sign_in_to", e.target.value)}
          />
        </div>
        <div className="field">
          <button type="submit" className="btn btn--primary">
            Search
          </button>
        </div>
      </form>

      {users.isPending && <Loading label="Loading users" />}
      {users.isError && <ErrorNotice error={users.error} />}
      {users.data && users.data.users.length === 0 && <p className="section">No users match.</p>}
      {users.data && users.data.users.length > 0 && (
        <section className="section" aria-label="Users">
          <p className="muted">
            {total} {total === 1 ? "user" : "users"}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Email</th>
                  <th scope="col">Status</th>
                  <th scope="col">Signed up</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">Plan</th>
                  <th scope="col" className="num">
                    Minutes left
                  </th>
                  <th scope="col">Consent</th>
                  <th scope="col" className="num">
                    Interviews
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.data.users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <Link to={`/users/${u.id}`}>{u.email}</Link>
                      {u.is_admin && <span className="tag"> Admin</span>}
                      {u.full_name && <div className="muted">{u.full_name}</div>}
                    </td>
                    <td>
                      <span className="status-pill" data-status={u.status}>
                        {u.status === "suspended" ? "Suspended" : "Active"}
                      </span>
                    </td>
                    <td>{utc(u.created_at)}</td>
                    <td>{utc(u.last_sign_in_at)}</td>
                    <td>
                      {u.plan === "paid" ? (u.comp_until && !u.subscription_status ? "Comp" : "Paid") : "Free"}
                      {u.subscription_status ? ` (${u.subscription_status})` : ""}
                    </td>
                    <td className="num">{u.plan === "paid" ? `${u.minutes_left} of ${u.minutes_cap}` : "-"}</td>
                    <td>{u.training_consent ? "Yes" : "No"}</td>
                    <td className="num">{u.interviews}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="row pager" aria-label="Pages">
            <button
              type="button"
              className="btn btn--small"
              disabled={page <= 1}
              onClick={() => setFilter("page", String(page - 1))}
            >
              Previous
            </button>
            <span className="muted">
              Page {page} of {pages}
            </span>
            <button
              type="button"
              className="btn btn--small"
              disabled={page >= pages}
              onClick={() => setFilter("page", String(page + 1))}
            >
              Next
            </button>
          </nav>
        </section>
      )}
    </>
  );
}
