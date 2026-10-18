import { useId, useState } from "react";
import { Link } from "react-router";

import {
  useCompanies,
  useCompanyRequests,
  useTriage,
  type CompanyRequestGroup,
  type TriageState,
} from "../api/content";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

const STATES: { value: TriageState; label: string }[] = [
  { value: "new", label: "New" },
  { value: "planned", label: "Planned" },
  { value: "declined", label: "Declined" },
  { value: "added", label: "Added" },
];

const stateLabel = (s: TriageState) => STATES.find((x) => x.value === s)?.label ?? s;

/** AT-5: names users asked for that are not curated, grouped by normalized name, with triage. */
export function CompanyRequestsPage() {
  const [filter, setFilter] = useState<TriageState | "">("");
  const requests = useCompanyRequests(filter || undefined);
  const [editing, setEditing] = useState<CompanyRequestGroup | null>(null);

  return (
    <>
      <PageHead title="Company requests">
        <p>
          Companies users entered at job setup that have no curated profile, most requested first. Request rows are
          never edited; triage is kept separately.
        </p>
      </PageHead>
      <div className="filters">
        <div className="field">
          <label htmlFor="triage-filter">Triage state</label>
          <select id="triage-filter" value={filter} onChange={(e) => setFilter(e.target.value as TriageState | "")}>
            <option value="">All</option>
            {STATES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {requests.isPending && <Loading label="Loading requests" />}
      {requests.isError && <ErrorNotice error={requests.error} />}
      {requests.data && requests.data.length === 0 && <p className="section">No requests.</p>}
      {requests.data && requests.data.length > 0 && (
        <div className="table-wrap section">
          <table>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col" className="num">
                  Users
                </th>
                <th scope="col" className="num">
                  Requests
                </th>
                <th scope="col">First</th>
                <th scope="col">Last</th>
                <th scope="col">Source hosts</th>
                <th scope="col">Triage</th>
              </tr>
            </thead>
            <tbody>
              {requests.data.map((g) => (
                <tr key={g.normalized_name}>
                  <td>
                    <strong>{g.normalized_name}</strong>
                    <div className="muted">{g.names.join(", ")}</div>
                  </td>
                  <td className="num">{g.users}</td>
                  <td className="num">{g.requests}</td>
                  <td>{utc(g.first_requested)}</td>
                  <td>{utc(g.last_requested)}</td>
                  <td>{g.source_hosts.length ? g.source_hosts.join(", ") : "-"}</td>
                  <td>
                    <span className="profile-status" data-status={g.triage.state}>
                      {stateLabel(g.triage.state)}
                    </span>
                    {g.triage.company_slug && (
                      <>
                        {" "}
                        <Link to={`/content/companies/${g.triage.company_slug}`}>{g.triage.company_slug}</Link>
                      </>
                    )}
                    {g.triage.note && <div className="muted">{g.triage.note}</div>}
                    <div>
                      <button
                        type="button"
                        className="btn btn--small"
                        aria-label={`Triage ${g.normalized_name}`}
                        onClick={() => setEditing(g)}
                      >
                        Triage
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <TriageDialog group={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function TriageDialog({ group, onClose }: { group: CompanyRequestGroup; onClose: () => void }) {
  const triage = useTriage();
  const companies = useCompanies();
  const [state, setState] = useState<TriageState>(group.triage.state);
  const [companyId, setCompanyId] = useState<string>(group.triage.company_id ?? "");
  const [note, setNote] = useState(group.triage.note ?? "");
  const ids = { state: useId(), company: useId(), note: useId() };
  const needsCompany = state === "added" && !companyId;

  return (
    <ReasonDialog
      title={`Triage "${group.normalized_name}"`}
      confirmLabel="Save triage"
      pending={triage.isPending}
      disabled={needsCompany}
      error={triage.error}
      onCancel={onClose}
      onConfirm={(reason) =>
        triage.mutate(
          {
            name: group.normalized_name,
            body: {
              state,
              company_id: state === "added" ? companyId : null,
              note: note.trim() || null,
              reason,
            },
          },
          { onSuccess: onClose },
        )
      }
    >
      <p className="muted">
        {group.users} users, {group.requests} requests.
      </p>
      <div className="field">
        <label htmlFor={ids.state}>State</label>
        <select id={ids.state} value={state} onChange={(e) => setState(e.target.value as TriageState)}>
          {STATES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {state === "added" && (
        <div className="field">
          <label htmlFor={ids.company}>Company it was added as</label>
          <select id={ids.company} value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            <option value="">Pick a company</option>
            {companies.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.slug})
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="field">
        <label htmlFor={ids.note}>Note</label>
        <input id={ids.note} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </div>
    </ReasonDialog>
  );
}
