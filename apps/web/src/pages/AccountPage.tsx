import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { accountApi } from "../api/account";
import { authApi } from "../api/auth";
import { billingApi } from "../api/billing";
import { keys, POLL_MS, useAuth, usePlan, useUsage } from "../api/hooks";
import type { AuthState, ExitReason, GotJob, Usage } from "../api/types";
import { ConsentSwitch } from "../components/ConsentSwitch";
import { ErrorNotice, PageHead } from "../components/ui";
import { formatDate } from "../labels";

const EXIT_REASONS: { value: ExitReason; label: string }[] = [
  { value: "got_the_job", label: "I got the job" },
  { value: "interview_over", label: "My interview is over" },
  { value: "too_expensive", label: "It costs too much" },
  { value: "not_helpful", label: "The practice did not help me" },
  { value: "technical_problems", label: "Technical problems" },
  { value: "missing_feature", label: "A feature I need is missing" },
  { value: "other", label: "Another reason" },
];

const GOT_JOB: { value: GotJob; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "still_interviewing", label: "I am still interviewing" },
  { value: "prefer_not_to_say", label: "I prefer not to say" },
];

/** BL-1: the plan, minutes and cancellation (with the two-question exit survey). */
function PlanSection({ usage }: { usage: Usage }) {
  const plan = usePlan();
  const [surveyOpen, setSurveyOpen] = useState(false);
  const [reason, setReason] = useState<ExitReason | "">("");
  const [gotJob, setGotJob] = useState<GotJob | "">("");
  const [detail, setDetail] = useState("");
  const [surveyError, setSurveyError] = useState<string | null>(null);

  const portal = useMutation({
    mutationFn: billingApi.portal,
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const survey = useMutation({
    mutationFn: billingApi.exitSurvey,
    onSuccess: () => portal.mutate("cancel"),
  });

  const onCancel = (e: FormEvent) => {
    e.preventDefault();
    if (!reason || !gotJob) {
      setSurveyError("Answer both questions, or skip the survey.");
      return;
    }
    setSurveyError(null);
    survey.mutate({ reason, got_job: gotJob, reason_detail: detail.trim() || null });
  };

  const busy = portal.isPending || survey.isPending;
  const paid = usage.plan === "paid";

  return (
    <section className="panel" aria-labelledby="plan-heading">
      <h2 id="plan-heading">Plan</h2>
      {paid ? (
        <dl className="dl">
          <dt>Plan</dt>
          <dd>{plan.data?.name ?? "Monthly plan"}</dd>
          <dt>Minutes this period</dt>
          <dd>
            {usage.minutes_used} of {usage.minutes_cap} used, {usage.minutes_left} left
          </dd>
          {usage.period_end && (
            <>
              <dt>{usage.cancel_at_period_end ? "Plan ends on" : "Renews on"}</dt>
              <dd>{formatDate(usage.period_end)}</dd>
            </>
          )}
        </dl>
      ) : (
        <p>
          Free plan. {usage.free_interviews_left} of {usage.free_interviews_total} free mini{" "}
          {usage.free_interviews_total === 1 ? "interview" : "interviews"} left. Gap analyses are free.{" "}
          <Link to="/upgrade">See the monthly plan</Link>
        </p>
      )}
      {usage.cancel_at_period_end && paid && (
        <p className="notice" role="status">
          Your plan is canceled. You can use your minutes until it ends.
        </p>
      )}

      <div className="row">
        {usage.has_billing_account && (
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => portal.mutate("manage")}
            disabled={busy}
          >
            Manage billing
          </button>
        )}
        {paid && !usage.cancel_at_period_end && !surveyOpen && (
          <button type="button" className="btn btn--quiet" onClick={() => setSurveyOpen(true)}>
            Cancel plan
          </button>
        )}
      </div>

      {paid && surveyOpen && !usage.cancel_at_period_end && (
        <form className="section" onSubmit={onCancel} aria-labelledby="survey-heading" noValidate>
          <h3 id="survey-heading">Before you go</h3>
          <p className="muted">Two questions help us improve. Then Stripe asks you to confirm the cancellation.</p>
          <fieldset>
            <legend>Why are you leaving?</legend>
            {EXIT_REASONS.map((o) => (
              <label key={o.value} className="check">
                <input
                  type="radio"
                  name="exit-reason"
                  value={o.value}
                  checked={reason === o.value}
                  onChange={() => setReason(o.value)}
                />
                <span>{o.label}</span>
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>Did you get the job?</legend>
            {GOT_JOB.map((o) => (
              <label key={o.value} className="check">
                <input
                  type="radio"
                  name="got-job"
                  value={o.value}
                  checked={gotJob === o.value}
                  onChange={() => setGotJob(o.value)}
                />
                <span>{o.label}</span>
              </label>
            ))}
          </fieldset>
          <div className="field">
            <label htmlFor="exit-detail">Anything else? (optional)</label>
            <textarea
              id="exit-detail"
              maxLength={1000}
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
            />
          </div>
          {surveyError && (
            <p className="field-error" role="alert">
              {surveyError}
            </p>
          )}
          <div className="row">
            <button type="submit" className="btn btn--danger" disabled={busy}>
              Continue to cancel
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => portal.mutate("cancel")} disabled={busy}>
              Skip the survey and cancel
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => setSurveyOpen(false)} disabled={busy}>
              Keep my plan
            </button>
          </div>
        </form>
      )}
      {(portal.isError || survey.isError) && <ErrorNotice error={portal.error ?? survey.error} />}
    </section>
  );
}

/** AC-1 (export, delete), AC-2 (consent) and BL-1 (plan and cancellation). */
export function AccountPage() {
  const auth = useAuth();
  const usage = useUsage();
  const user = auth.data?.user;
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const consent = useMutation({
    mutationFn: accountApi.setConsent,
    onSuccess: ({ training_consent }) => {
      queryClient.setQueryData<AuthState>(keys.me, (prev) =>
        prev?.user ? { ...prev, user: { ...prev.user, training_consent } } : prev,
      );
    },
  });

  const [exportId, setExportId] = useState<string | null>(null);
  const startExport = useMutation({ mutationFn: accountApi.startExport, onSuccess: (job) => setExportId(job.id) });
  const exportJob = useQuery({
    queryKey: ["account", "export", exportId],
    queryFn: () => accountApi.getExport(exportId ?? ""),
    enabled: Boolean(exportId),
    refetchInterval: (q) => (q.state.data && q.state.data.status !== "preparing" ? false : POLL_MS),
  });
  const exportStatus = exportJob.data?.status;
  const exportDone = exportStatus !== undefined && exportStatus !== "preparing" && exportStatus !== "ready";

  const [confirmText, setConfirmText] = useState("");
  const remove = useMutation({
    mutationFn: async () => {
      await accountApi.deleteAccount();
      await authApi.logout().catch(() => undefined);
    },
    onSuccess: () => {
      queryClient.clear();
      navigate("/signin?deleted=1");
    },
  });

  if (!user) return null;
  const consentValue = consent.isPending ? (consent.variables ?? user.training_consent) : user.training_consent;

  return (
    <div className="page--narrow">
      <PageHead title="Account" />
      <section className="panel" aria-labelledby="profile-heading">
        <h2 id="profile-heading">Profile</h2>
        <dl className="dl">
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Member since</dt>
          <dd>{formatDate(user.created_at)}</dd>
        </dl>
      </section>

      {usage.data && <PlanSection usage={usage.data} />}
      {usage.isError && <ErrorNotice error={usage.error} />}

      <section className="panel" aria-labelledby="privacy-heading">
        <h2 id="privacy-heading">Training data</h2>
        <ConsentSwitch checked={consentValue} onChange={(v) => consent.mutate(v)} disabled={consent.isPending} />
        <p role="status" className="muted">
          {consent.isSuccess && `Saved. Training-data use is ${consentValue ? "on" : "off"}.`}
        </p>
        {consent.isError && <ErrorNotice error={consent.error} />}
      </section>

      <section className="panel" aria-labelledby="export-heading">
        <h2 id="export-heading">Export your data</h2>
        <p>
          Download all your data as a zip file: a JSON file with every record, and your original resume files. The
          download link works once, for 24 hours.
        </p>
        {exportStatus === "ready" && exportJob.data?.download_url ? (
          <a
            className="btn"
            href={exportJob.data.download_url}
            download="strong-hire-export.zip"
            // The link works once. Check the status again after the browser starts the download.
            onClick={() => window.setTimeout(() => void exportJob.refetch(), 1500)}
          >
            Download export
          </a>
        ) : (
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => {
              setExportId(null);
              startExport.mutate();
            }}
            disabled={startExport.isPending || exportStatus === "preparing" || (Boolean(exportId) && !exportDone)}
          >
            {exportId && !exportDone ? "Preparing your export" : "Prepare export"}
          </button>
        )}
        <p role="status" className={exportDone ? "muted" : "visually-hidden"}>
          {exportStatus === "ready" && "Your export is ready to download."}
          {exportStatus === "downloaded" && "Your export was downloaded. Prepare a new one to download again."}
          {exportStatus === "expired" && "Your export link has expired. Prepare a new one."}
        </p>
        {exportStatus === "failed" && (
          <ErrorNotice error={exportJob.data?.error ?? "The export failed."} title="We could not prepare your export." />
        )}
        {(startExport.isError || exportJob.isError) && <ErrorNotice error={startExport.error ?? exportJob.error} />}
      </section>

      <section className="panel" aria-labelledby="delete-heading">
        <h2 id="delete-heading">Delete your account</h2>
        <p>
          This deletes your account, resumes, jobs, transcripts and scores within 24 hours, and cancels your plan.
          Backups expire within 30 days. You cannot undo this.
        </p>
        <div className="field">
          <label htmlFor="delete-confirm">Type DELETE to confirm</label>
          <input
            id="delete-confirm"
            type="text"
            autoComplete="off"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
          />
        </div>
        {remove.isError && <ErrorNotice error={remove.error} />}
        <button
          type="button"
          className="btn btn--danger"
          disabled={confirmText !== "DELETE" || remove.isPending}
          onClick={() => remove.mutate()}
        >
          Delete my account
        </button>
      </section>
    </div>
  );
}
