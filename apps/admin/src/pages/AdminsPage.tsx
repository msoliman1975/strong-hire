import { useState, type FormEvent } from "react";

import { useAuth } from "../api/hooks";
import { useAddAdmin, useAdmins, useRemoveAdmin } from "../api/settings";
import type { AdminAccount } from "../api/types";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

/**
 * Settings > Admins (AA-1, AA-8): who may use the admin app. Adding and removing take a reason
 * (AA-6) and a confirmation that repeats the email (AA-7). Removing an admin ends their sessions.
 */
export function AdminsPage() {
  const me = useAuth();
  const admins = useAdmins();
  const add = useAddAdmin();
  const remove = useRemoveAdmin();
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AdminAccount | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const startAdd = (e: FormEvent) => {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    if (!value) return;
    add.reset();
    setAdding(value);
  };

  return (
    <>
      <PageHead title="Admins">
        <p>
          Everyone who may use the admin app. They sign in with Google, an email link, or the password of their account.
        </p>
      </PageHead>

      {notice && (
        <div className="notice" role="status">
          <p>{notice}</p>
        </div>
      )}

      <form className="add-admin" onSubmit={startAdd} aria-label="Add an admin">
        <div className="field">
          <label htmlFor="new-admin">Email address</label>
          <input id="new-admin" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <button type="submit" className="btn btn--primary">
          Add admin
        </button>
      </form>

      {admins.isPending && <Loading label="Loading admins" />}
      {admins.isError && <ErrorNotice error={admins.error} />}
      {admins.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Status</th>
                <th scope="col">Added by</th>
                <th scope="col">Added</th>
                <th scope="col" className="num">
                  Live sessions
                </th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {admins.data.map((a) => {
                const self = a.id === me.data?.id;
                return (
                  <tr key={a.id}>
                    <td>
                      {a.email}
                      {self && <span className="tag"> You</span>}
                    </td>
                    <td>{a.disabled_at ? `Removed ${utc(a.disabled_at)}` : "Active"}</td>
                    <td>{a.added_by ?? "-"}</td>
                    <td>{utc(a.added_at)}</td>
                    <td className="num">{a.live_sessions}</td>
                    <td>
                      {!a.disabled_at && !self && (
                        <button
                          type="button"
                          className="btn btn--small"
                          aria-label={`Remove ${a.email}`}
                          onClick={() => {
                            remove.reset();
                            setRemoving(a);
                          }}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {adding && (
        <ReasonDialog
          title="Add an admin"
          confirmLabel={`Add ${adding}`}
          pending={add.isPending}
          error={add.error}
          onCancel={() => setAdding(null)}
          onConfirm={(reason) =>
            add.mutate(
              { email: adding, reason },
              {
                onSuccess: (row) => {
                  setAdding(null);
                  setEmail("");
                  setNotice(`${row.email} is now an admin.`);
                },
              },
            )
          }
        >
          <p>
            <strong>{adding}</strong> will be able to sign in to the admin app and use every admin action.
          </p>
        </ReasonDialog>
      )}

      {removing && (
        <ReasonDialog
          title="Remove an admin"
          confirmLabel={`Remove ${removing.email}`}
          danger
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => setRemoving(null)}
          onConfirm={(reason) =>
            remove.mutate(
              { id: removing.id, reason },
              {
                onSuccess: (row) => {
                  setRemoving(null);
                  setNotice(`${row.email} was removed and signed out.`);
                },
              },
            )
          }
        >
          <p>
            <strong>{removing.email}</strong> will no longer be able to sign in. Their {removing.live_sessions} live
            session{removing.live_sessions === 1 ? "" : "s"} end now.
          </p>
        </ReasonDialog>
      )}
    </>
  );
}
