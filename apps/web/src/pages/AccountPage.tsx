import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { keys, POLL_MS, useAuth } from "../api/hooks";
import { accountApi } from "../api/planned";
import type { AuthState } from "../api/types";
import { ConsentSwitch } from "../components/ConsentSwitch";
import { ErrorNotice, PageHead } from "../components/ui";
import { formatDate } from "../labels";

/** AC-1 (export, delete) and AC-2 (consent). */
export function AccountPage() {
  const auth = useAuth();
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
    refetchInterval: (q) => (q.state.data?.status === "ready" ? false : POLL_MS),
  });

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
        <p>Download all your data as JSON, with your original resume files. The download link works once.</p>
        {exportJob.data?.status === "ready" && exportJob.data.download_url ? (
          <a className="btn" href={exportJob.data.download_url} download="strong-hire-export.json">
            Download export
          </a>
        ) : (
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => startExport.mutate()}
            disabled={startExport.isPending || Boolean(exportId)}
          >
            {exportId ? "Preparing your export" : "Prepare export"}
          </button>
        )}
        <p role="status" className="visually-hidden">
          {exportJob.data?.status === "ready" ? "Your export is ready to download." : ""}
        </p>
        {(startExport.isError || exportJob.isError) && <ErrorNotice error={startExport.error ?? exportJob.error} />}
      </section>

      <section className="panel" aria-labelledby="delete-heading">
        <h2 id="delete-heading">Delete your account</h2>
        <p>
          This deletes your account, resumes, jobs, transcripts and scores within 24 hours. Backups expire within 30
          days. You cannot undo this.
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
