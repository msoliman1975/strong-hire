import { useState } from "react";

import { type AuditScope, useAdminAudit } from "../../api/admin";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { utc } from "./format";

/** The audit log (R2). By default only admin views of transcripts and traces. */
export function AdminAuditPage() {
  const [scope, setScope] = useState<AuditScope>("admin");
  const audit = useAdminAudit(scope);
  return (
    <>
      <PageHead title="Audit log">
        <p>Each time an admin opens a transcript or the interviewer reasoning, a row is added here.</p>
      </PageHead>
      <fieldset>
        <legend className="label">Show</legend>
        <div className="row">
          <label className="check">
            <input type="radio" name="scope" checked={scope === "admin"} onChange={() => setScope("admin")} />
            Admin views
          </label>
          <label className="check">
            <input type="radio" name="scope" checked={scope === "all"} onChange={() => setScope("all")} />
            All entries
          </label>
        </div>
      </fieldset>
      {audit.isPending && <Loading label="Loading the audit log" />}
      {audit.isError && <ErrorNotice error={audit.error} />}
      {audit.data && audit.data.length === 0 && <p>No entries yet.</p>}
      {audit.data && audit.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">What</th>
                <th scope="col">Which</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.map((a) => (
                <tr key={a.id}>
                  <td>{utc(a.at)}</td>
                  <td>{a.actor}</td>
                  <td>{a.action}</td>
                  <td>{a.entity}</td>
                  <td className="details-json">{a.details ? JSON.stringify(a.details) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
