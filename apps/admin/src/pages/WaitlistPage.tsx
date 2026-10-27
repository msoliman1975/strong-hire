import { useState } from "react";

import { useOpsSettings } from "../api/controls";
import {
  useInviteWaitlist,
  useWaitlist,
  waitlistApi,
  type AdminWaitlistEntry,
  type InviteResult,
} from "../api/waitlist";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";
import { roleFamilyLabel } from "../labels";

const WHEN: Record<AdminWaitlistEntry["interview_within"], string> = {
  two_weeks: "Within 2 weeks",
  month: "Within a month",
  later: "Later",
  not_yet: "Not booked",
};

/** How many chosen emails the confirm dialog lists before it says "and N more". */
const LISTED = 10;

function resultText(r: InviteResult): string {
  const parts = [`Sent ${r.sent.length} ${r.sent.length === 1 ? "invite" : "invites"}.`];
  if (r.skipped.length > 0) parts.push(`Skipped (not confirmed): ${r.skipped.join(", ")}.`);
  if (r.failed.length > 0) parts.push(`Could not send, try again: ${r.failed.join(", ")}.`);
  return parts.join(" ");
}

/**
 * L04: people waiting for sign-ups to open, from the public waitlist page. Admins pick confirmed
 * entries and send them the "Strong Hire is ready for you" invite, with a reason (AA-6).
 */
export function WaitlistPage() {
  const waitlist = useWaitlist();
  const ops = useOpsSettings();
  const invite = useInviteWaitlist();
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<InviteResult | null>(null);

  const entries = waitlist.data?.entries ?? [];
  const invitable = entries.filter((e) => e.confirmed_at);
  const picked = entries.filter((e) => chosen.has(e.id));
  const reinvites = picked.filter((e) => e.invited_at).length;
  const paused = ops.data?.values.signups_paused ?? false;
  const allChosen = invitable.length > 0 && invitable.every((e) => chosen.has(e.id));

  const toggle = (id: string, on: boolean) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <>
      <PageHead title="Waitlist">
        <p>People who joined from the public waitlist page. Only confirmed emails can get an invite.</p>
        <p>
          Nobody is emailed automatically when sign-ups open. Tick the people to let in and choose Invite: each gets
          a "Strong Hire is ready for you" email with the sign-in link. Each admin gets an email when someone new
          joins.
        </p>
      </PageHead>
      <div className="row section-actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={picked.length === 0 || paused}
          onClick={() => {
            invite.reset();
            setConfirming(true);
          }}
        >
          Invite {picked.length > 0 ? `${picked.length} selected` : "selected"}
        </button>
        <a className="btn" href={waitlistApi.csvUrl} download>
          Download CSV
        </a>
      </div>
      {paused && (
        <p className="notice" role="status">
          Sign-ups are paused, so invites are off. Open sign-ups on Controls first.
        </p>
      )}
      {result && (
        <p className="notice" role="status">
          {resultText(result)}
        </p>
      )}

      {waitlist.isPending && <Loading label="Loading the waitlist" />}
      {waitlist.isError && <ErrorNotice error={waitlist.error} />}
      {waitlist.data && (
        <>
          <div className="kpis">
            <div className="kpi">
              <p className="kpi__label">Joined</p>
              <p className="kpi__value">{waitlist.data.total}</p>
            </div>
            <div className="kpi">
              <p className="kpi__label">Confirmed</p>
              <p className="kpi__value">{waitlist.data.confirmed}</p>
            </div>
            <div className="kpi">
              <p className="kpi__label">Invited</p>
              <p className="kpi__value">{entries.filter((e) => e.invited_at).length}</p>
            </div>
            <div className="kpi">
              <p className="kpi__label">Want product news</p>
              <p className="kpi__value">{waitlist.data.marketing_consent}</p>
            </div>
          </div>
          {entries.length === 0 ? (
            <p className="section">No one has joined yet.</p>
          ) : (
            <div className="table-wrap section">
              <table aria-label="Waitlist entries">
                <thead>
                  <tr>
                    <th scope="col">
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={allChosen}
                          disabled={invitable.length === 0}
                          onChange={(e) => setChosen(e.target.checked ? new Set(invitable.map((x) => x.id)) : new Set())}
                        />
                        <span className="visually-hidden">Select every confirmed entry</span>
                      </label>
                    </th>
                    <th scope="col">Email</th>
                    <th scope="col">Interview</th>
                    <th scope="col">Field</th>
                    <th scope="col">Confirmed</th>
                    <th scope="col">Invited</th>
                    <th scope="col">News</th>
                    <th scope="col">Source</th>
                    <th scope="col">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <label className="check">
                          <input
                            type="checkbox"
                            checked={chosen.has(e.id)}
                            disabled={!e.confirmed_at}
                            onChange={(ev) => toggle(e.id, ev.target.checked)}
                          />
                          <span className="visually-hidden">Select {e.email}</span>
                        </label>
                      </td>
                      <td>{e.email}</td>
                      <td>{WHEN[e.interview_within]}</td>
                      <td>{e.role_family ? roleFamilyLabel[e.role_family] : "-"}</td>
                      <td>{e.confirmed_at ? utc(e.confirmed_at) : "No"}</td>
                      <td>{e.invited_at ? utc(e.invited_at) : "No"}</td>
                      <td>{e.marketing_consent ? "Yes" : "No"}</td>
                      <td>{e.source ?? "-"}</td>
                      <td>{utc(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {confirming && (
        <ReasonDialog
          title="Invite to sign up"
          confirmLabel={`Send ${picked.length} ${picked.length === 1 ? "invite" : "invites"}`}
          pending={invite.isPending}
          error={invite.error}
          onCancel={() => setConfirming(false)}
          onConfirm={(reason) =>
            invite.mutate(
              { ids: picked.map((e) => e.id), reason },
              {
                onSuccess: (r) => {
                  setResult(r);
                  setChosen(new Set());
                  setConfirming(false);
                },
              },
            )
          }
        >
          <p>Each person gets their own "Strong Hire is ready for you" email with the link to sign in:</p>
          <ul>
            {picked.slice(0, LISTED).map((e) => (
              <li key={e.id}>{e.email}</li>
            ))}
            {picked.length > LISTED && <li>and {picked.length - LISTED} more</li>}
          </ul>
          {reinvites > 0 && (
            <p>
              {reinvites} of them {reinvites === 1 ? "was" : "were"} invited before and will get the email again.
            </p>
          )}
        </ReasonDialog>
      )}
    </>
  );
}
