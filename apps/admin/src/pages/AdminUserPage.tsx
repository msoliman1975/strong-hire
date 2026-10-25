import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import {
  type AdminGrant,
  type AdminUserDetail,
  type GrantKind,
  useUserAction,
  useUserDetail,
  usersApi,
} from "../api/users";
import { ActionDialog } from "../components/ActionDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { interviewTypeLabel } from "../labels";
import { money, utc, words } from "../format";

type Dialog =
  | { kind: "grant"; grant: GrantKind }
  | { kind: "revoke"; grant: AdminGrant }
  | { kind: "suspend" | "unsuspend" | "signout" | "resend" };

const GRANT_TITLES: Record<GrantKind, string> = {
  minutes: "Grant minutes",
  free_interviews: "Grant free interviews",
  comp_plan: "Give a comp plan",
};

/** A grant in words, repeating the amount (AA-7). */
export function grantText(kind: GrantKind, amount: number): string {
  if (kind === "minutes") return amount < 0 ? `remove ${-amount} minutes` : `${amount} extra minutes`;
  if (kind === "free_interviews") return `${amount} extra free ${amount === 1 ? "interview" : "interviews"}`;
  return `a comp plan with ${amount} minutes`;
}

/** The end of a chosen day, in UTC. */
function endOfDay(day: string): string {
  return `${day}T23:59:59Z`;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

function GrantFields({
  kind,
  amount,
  setAmount,
  until,
  setUntil,
}: {
  kind: GrantKind;
  amount: string;
  setAmount: (v: string) => void;
  until: string;
  setUntil: (v: string) => void;
}) {
  const amountLabel =
    kind === "minutes"
      ? "Minutes (negative removes minutes)"
      : kind === "free_interviews"
        ? "Free interviews"
        : "Minute cap of the comp plan";
  return (
    <>
      <div className="field">
        <label htmlFor="grant-amount">{amountLabel}</label>
        <input
          id="grant-amount"
          type="number"
          inputMode="numeric"
          min={kind === "minutes" ? -10000 : 1}
          max={kind === "free_interviews" ? 100 : 10000}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="grant-until">{kind === "comp_plan" ? "Paid access until (UTC)" : "Expires on (optional, UTC)"}</label>
        <input id="grant-until" type="date" min={today()} value={until} onChange={(e) => setUntil(e.target.value)} />
      </div>
    </>
  );
}

function amountProblem(kind: GrantKind, value: number): string | null {
  if (!Number.isInteger(value)) return "Enter a whole number.";
  if (kind === "minutes" && (value === 0 || Math.abs(value) > 10000)) return "Enter -10000 to 10000, not 0.";
  if (kind === "free_interviews" && (value < 1 || value > 100)) return "Enter 1 to 100.";
  if (kind === "comp_plan" && (value < 1 || value > 10000)) return "Enter 1 to 10000.";
  return null;
}

function Actions({ detail }: { detail: AdminUserDetail }) {
  const u = detail.user;
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [amount, setAmount] = useState("");
  const [until, setUntil] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const action = useUserAction();

  const open = (next: Dialog) => {
    action.reset();
    setAmount("");
    setUntil("");
    setDialog(next);
  };
  const close = () => setDialog(null);
  const run = (fn: () => Promise<unknown>, message: string) =>
    action.mutate(fn, {
      onSuccess: () => {
        setDialog(null);
        setDone(message);
      },
    });

  const grantKind = dialog?.kind === "grant" ? dialog.grant : null;
  const amountValue = Number(amount);
  const grantProblem = grantKind ? (amount === "" ? "Enter an amount." : amountProblem(grantKind, amountValue)) : null;
  const grantReady = grantKind !== null && grantProblem === null && (grantKind !== "comp_plan" || until !== "");

  return (
    <>
      <div className="row action-bar" role="group" aria-label="Support actions">
        <button type="button" className="btn btn--small" onClick={() => open({ kind: "grant", grant: "minutes" })}>
          Grant minutes
        </button>
        <button type="button" className="btn btn--small" onClick={() => open({ kind: "grant", grant: "free_interviews" })}>
          Grant free interviews
        </button>
        <button type="button" className="btn btn--small" onClick={() => open({ kind: "grant", grant: "comp_plan" })}>
          Comp plan
        </button>
        <button type="button" className="btn btn--small" onClick={() => open({ kind: "resend" })}>
          Resend sign-in link
        </button>
        <button type="button" className="btn btn--small" onClick={() => open({ kind: "signout" })}>
          Force sign-out
        </button>
        {u.status === "suspended" ? (
          <button type="button" className="btn btn--small" onClick={() => open({ kind: "unsuspend" })}>
            Unsuspend
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--small btn--danger-outline"
            onClick={() => open({ kind: "suspend" })}
            disabled={u.is_admin}
            title={u.is_admin ? "Admins cannot be suspended" : undefined}
          >
            Suspend
          </button>
        )}
      </div>
      {done && (
        <p className="notice" role="status">
          {done}
        </p>
      )}

      {grantKind && (
        <ActionDialog
          open
          title={GRANT_TITLES[grantKind]}
          summary={
            <p>
              Give <strong>{u.email}</strong>{" "}
              <strong>{grantProblem ? "..." : grantText(grantKind, amountValue)}</strong>
              {until ? ` until ${until} (UTC)` : grantKind === "comp_plan" ? " until the date below" : ", with no end date"}.
            </p>
          }
          confirmLabel={GRANT_TITLES[grantKind]}
          canConfirm={grantReady}
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) =>
            run(
              () =>
                usersApi.grant(u.id, {
                  kind: grantKind,
                  amount: amountValue,
                  expires_at: until ? endOfDay(until) : null,
                  reason,
                }),
              `Done: ${grantText(grantKind, amountValue)} for ${u.email}.`,
            )
          }
        >
          <GrantFields kind={grantKind} amount={amount} setAmount={setAmount} until={until} setUntil={setUntil} />
          {amount !== "" && grantProblem && <p className="muted">{grantProblem}</p>}
        </ActionDialog>
      )}

      {dialog?.kind === "revoke" && (
        <ActionDialog
          open
          danger
          title="Revoke grant"
          summary={
            <p>
              Revoke <strong>{grantText(dialog.grant.kind, dialog.grant.amount)}</strong> from <strong>{u.email}</strong>.
              It stops counting now and stays in the history.
            </p>
          }
          confirmLabel="Revoke grant"
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) =>
            run(() => usersApi.revokeGrant(u.id, dialog.grant.id, reason), `Grant revoked for ${u.email}.`)
          }
        />
      )}

      {dialog?.kind === "suspend" && (
        <ActionDialog
          open
          danger
          title="Suspend user"
          summary={
            <>
              <p>
                Suspend <strong>{u.email}</strong>?
              </p>
              <p>
                Their requests and sign-ins are refused with a neutral message, and any interview in progress ends now
                (billed and scored as usual).
              </p>
            </>
          }
          confirmLabel={`Suspend ${u.email}`}
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) => run(() => usersApi.suspend(u.id, reason), `${u.email} is suspended.`)}
        />
      )}

      {dialog?.kind === "unsuspend" && (
        <ActionDialog
          open
          title="Unsuspend user"
          summary={
            <p>
              Let <strong>{u.email}</strong> sign in and use Strong Hire again.
            </p>
          }
          confirmLabel="Unsuspend"
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) => run(() => usersApi.unsuspend(u.id, reason), `${u.email} is active again.`)}
        />
      )}

      {dialog?.kind === "signout" && (
        <ActionDialog
          open
          danger
          title="Force sign-out"
          summary={
            <p>
              Sign <strong>{u.email}</strong> out on every device. They can sign in again.
            </p>
          }
          confirmLabel="Sign out everywhere"
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) => run(() => usersApi.signOut(u.id, reason), `${u.email} is signed out everywhere.`)}
        />
      )}

      {dialog?.kind === "resend" && (
        <ActionDialog
          open
          title="Resend sign-in link"
          summary={
            <p>
              Email a sign-in link to <strong>{u.email}</strong>. Only they receive it.
            </p>
          }
          confirmLabel="Send link"
          pending={action.isPending}
          error={action.error}
          onCancel={close}
          onConfirm={(reason) => run(() => usersApi.resendLink(u.id, reason), `Sign-in link sent to ${u.email}.`)}
        />
      )}

      <Section id="grants" title="Grants">
        {detail.grants.length === 0 ? (
          <p>No grants.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Grant</th>
                  <th scope="col">State</th>
                  <th scope="col">Expires</th>
                  <th scope="col">By</th>
                  <th scope="col">Reason</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {detail.grants.map((g) => (
                  <tr key={g.id}>
                    <td>{grantText(g.kind, g.amount)}</td>
                    <td>{g.revoked_at ? `Revoked ${utc(g.revoked_at)}` : g.active ? "Active" : "Expired"}</td>
                    <td>{utc(g.expires_at)}</td>
                    <td>
                      {g.granted_by}
                      <div className="muted">{utc(g.created_at)}</div>
                    </td>
                    <td>{g.reason}</td>
                    <td>
                      {g.active && (
                        <button
                          type="button"
                          className="btn btn--small"
                          onClick={() => open({ kind: "revoke", grant: g })}
                          aria-label={`Revoke ${grantText(g.kind, g.amount)}`}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

function Overview({ detail }: { detail: AdminUserDetail }) {
  const { user: u, profile: p, entitlement: e, subscription: s } = detail;
  return (
    <div className="grid-2 section">
      <section aria-labelledby="profile">
        <h2 id="profile">Profile</h2>
        <dl className="dl panel">
          <dt>User id</dt>
          <dd>{u.id}</dd>
          <dt>Name</dt>
          <dd>{p.full_name ?? "-"}</dd>
          <dt>Title</dt>
          <dd>{p.current_title ?? "-"}</dd>
          <dt>Target level</dt>
          <dd>{p.target_level ? words(p.target_level) : "-"}</dd>
          <dt>Country</dt>
          <dd>{p.country ?? "-"}</dd>
          <dt>Sign-in</dt>
          <dd>
            {u.auth_provider}
            {p.has_password ? ", password set" : ""}
            {p.email_verified_at ? "" : ", email not confirmed"}
          </dd>
          <dt>Signed up</dt>
          <dd>{utc(u.created_at)}</dd>
          <dt>Last sign-in</dt>
          <dd>{utc(u.last_sign_in_at)}</dd>
          <dt>Training consent</dt>
          <dd>{u.training_consent ? "Yes" : "No"}</dd>
          <dt>Org</dt>
          <dd>{detail.org ? `${detail.org.name} (${detail.org.type})` : "-"}</dd>
          {u.status === "suspended" && (
            <>
              <dt>Suspended</dt>
              <dd>
                {utc(u.suspended_at)}: {detail.suspended_reason ?? "-"}
              </dd>
            </>
          )}
        </dl>
      </section>
      <section aria-labelledby="plan">
        <h2 id="plan">Plan</h2>
        <dl className="dl panel">
          <dt>Plan</dt>
          <dd>
            {e.plan === "paid" ? (s && ["active", "trialing"].includes(s.status) ? "Paid" : "Comp") : "Free"}
            {e.comp_until ? ` (comp until ${utc(e.comp_until)})` : ""}
          </dd>
          <dt>Minutes</dt>
          <dd>
            {e.plan === "paid"
              ? `${e.minutes_left} left: ${e.plan_minutes_cap} plan + ${e.minutes_granted} granted - ${e.minutes_used} used`
              : "-"}
          </dd>
          <dt>Free interviews</dt>
          <dd>
            {e.free_interviews_left} left of {e.free_interviews_total}
            {e.free_interviews_granted ? ` (${e.free_interviews_granted} granted)` : ""}
          </dd>
          <dt>Blocked</dt>
          <dd>{e.block_code ? words(e.block_code) : "No"}</dd>
          <dt>Subscription</dt>
          <dd>{s ? `${words(s.status)}${s.cancel_at_period_end ? ", cancels at period end" : ""}` : "None"}</dd>
          {s && (
            <>
              <dt>Period</dt>
              <dd>
                {utc(s.period_start)} to {utc(s.period_end)}
              </dd>
              <dt>Stripe customer</dt>
              <dd>
                {s.stripe_customer_url ? (
                  <a href={s.stripe_customer_url} target="_blank" rel="noreferrer noopener">
                    {s.stripe_customer_id}
                  </a>
                ) : (
                  (s.stripe_customer_id ?? "-")
                )}
                {s.stripe_mode && <span className="muted"> ({s.stripe_mode} mode)</span>}
              </dd>
              <dt>Stripe subscription</dt>
              <dd>{s.stripe_subscription_id ?? "-"}</dd>
            </>
          )}
          <dt>Model cost to date</dt>
          <dd>
            {money(detail.cost_to_date_usd)}
            {detail.cost_unknown_events > 0 && (
              <span className="muted"> ({detail.cost_unknown_events} usage rows without a price)</span>
            )}
          </dd>
        </dl>
      </section>
    </div>
  );
}

function Lists({ detail }: { detail: AdminUserDetail }) {
  return (
    <>
      <Section id="refunds" title="Refunds">
        <p className="muted">Refunds are made in the Stripe dashboard (D-7). They show here from the webhook.</p>
        {detail.refunds.length === 0 ? (
          <p>No refunds.</p>
        ) : (
          <ul>
            {detail.refunds.map((r) => (
              <li key={`${r.charge_id}-${r.at}`}>
                {utc(r.at)}: {r.amount_refunded === null ? "?" : (r.amount_refunded / 100).toFixed(2)}{" "}
                {r.currency?.toUpperCase() ?? ""} on {r.charge_id ?? "a charge"}
                {r.livemode ? "" : " (test mode)"}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="interviews" title="Interviews">
        {detail.sessions.length === 0 ? (
          <p>No interviews.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Type</th>
                  <th scope="col">Channel</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Minutes
                  </th>
                  <th scope="col" className="num">
                    Cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {detail.sessions.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Link to={`/interviews/${s.id}`}>{utc(s.created_at)}</Link>
                    </td>
                    <td>{interviewTypeLabel[s.interview_type]}</td>
                    <td>{s.channel}</td>
                    <td>{words(s.status)}</td>
                    <td className="num">{s.minutes_billed}</td>
                    <td className="num">{money(s.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="jobs" title="Job targets">
        {detail.job_targets.length === 0 ? (
          <p>No job targets.</p>
        ) : (
          <ul>
            {detail.job_targets.map((j) => (
              <li key={j.id}>
                {j.company ?? "Unknown company"}: {j.title ?? "untitled"}
                {j.level ? `, ${words(j.level)}` : ""} <span className="muted">({utc(j.created_at)})</span>
                {j.deleted_at && <span className="muted"> deleted</span>}
                {j.archived_at && !j.deleted_at && <span className="muted"> archived</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="docs" title="CVs and gap analyses">
        <p className="muted">Metadata only. Admins never see CV or gap analysis content (D-8).</p>
        <p>
          {detail.resume_count} {detail.resume_count === 1 ? "CV" : "CVs"}, {detail.gap_analysis_count}{" "}
          {detail.gap_analysis_count === 1 ? "gap analysis" : "gap analyses"}.
        </p>
        {detail.resumes.length > 0 && (
          <ul aria-label="CVs">
            {detail.resumes.map((r) => (
              <li key={r.id}>
                CV uploaded {utc(r.uploaded_at)}: {words(r.status)}
                {r.deleted_at ? ` on ${utc(r.deleted_at)}` : ""}
              </li>
            ))}
          </ul>
        )}
        {detail.gap_analyses.length > 0 && (
          <ul aria-label="Gap analyses">
            {detail.gap_analyses.map((g) => (
              <li key={g.id}>
                Gap analysis {utc(g.created_at)}: {words(g.status)}
                {g.has_error && <strong> (error)</strong>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="privacy" title="Privacy requests">
        <p className="muted">The user runs exports and deletes in the candidate app (D-5).</p>
        {detail.privacy_actions.length === 0 ? (
          <p>None.</p>
        ) : (
          <ul>
            {detail.privacy_actions.map((a) => (
              <li key={a.id}>
                {utc(a.at)}: {words(a.action.replace("account.", ""))}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="audit" title="Audit log">
        {detail.audit.length === 0 ? (
          <p>No entries.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">Action</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {detail.audit.map((a) => (
                  <tr key={a.id}>
                    <td>{utc(a.at)}</td>
                    <td>{a.actor}</td>
                    <td>{a.action}</td>
                    <td>{typeof a.details?.reason === "string" ? a.details.reason : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

/** AU-2: one user, with the support actions (AU-3..AU-9). */
export function AdminUserPage() {
  const { userId = "" } = useParams();
  const detail = useUserDetail(userId);
  return (
    <>
      <p>
        <Link to="/users">All users</Link>
      </p>
      {detail.isPending && <Loading label="Loading the user" />}
      {detail.isError && <ErrorNotice error={detail.error} />}
      {detail.data && (
        <>
          <PageHead title={detail.data.user.email}>
            <p>
              <span className="status-pill" data-status={detail.data.user.status}>
                {detail.data.user.status === "suspended" ? "Suspended" : "Active"}
              </span>
              {detail.data.user.is_admin && <span className="tag"> Admin</span>}
            </p>
          </PageHead>
          <Overview detail={detail.data} />
          <Actions detail={detail.data} />
          <Lists detail={detail.data} />
        </>
      )}
    </>
  );
}
