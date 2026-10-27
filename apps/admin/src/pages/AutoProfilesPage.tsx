import { useId, useState } from "react";

import {
  part1Api,
  useAutoProfileAction,
  useAutoProfiles,
  type AdminAutoProfile,
  type AutoProfileFilter,
} from "../api/part1";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

const FILTERS: { key: AutoProfileFilter; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "retired", label: "Retired" },
  { key: "all", label: "All" },
];

const STATUS_LABEL: Record<AdminAutoProfile["status"], string> = {
  pending: "Pending",
  approved: "Approved",
  retired: "Retired",
};

type Pending =
  | { kind: "approve"; row: AdminAutoProfile }
  | { kind: "edit"; row: AdminAutoProfile }
  | { kind: "retire"; row: AdminAutoProfile };

function SummaryField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>Summary</label>
      <textarea id={id} rows={6} maxLength={2000} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function ProfileCard({ row, onAction }: { row: AdminAutoProfile; onAction: (p: Pending) => void }) {
  return (
    <article className="panel section" aria-labelledby={`ap-${row.id}`}>
      <div className="row">
        <h2 id={`ap-${row.id}`}>{row.company_name}</h2>
        <span className={row.status === "retired" ? "state state--off" : "state state--on"}>{STATUS_LABEL[row.status]}</span>
      </div>
      <p className="muted small">
        From {row.source_host}, built {utc(row.created_at)} ({row.prompt_version}, {row.model_profile})
        {row.reviewed_by && (
          <>
            . Last reviewed by {row.reviewed_by}, {utc(row.reviewed_at)}
          </>
        )}
      </p>
      <p>{row.summary}</p>
      {row.values_mentioned.length > 0 && (
        <p>
          <strong>Values:</strong> {row.values_mentioned.join(" · ")}
        </p>
      )}
      {row.interview_process_notes.length > 0 && (
        <>
          <p>
            <strong>Interview process:</strong>
          </p>
          <ul>
            {row.interview_process_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
      <p>
        <strong>Sources:</strong>
      </p>
      <ul aria-label={`Sources for ${row.company_name}`}>
        {row.sources.map((s) => (
          <li key={s}>
            <a href={s} target="_blank" rel="noreferrer noopener">
              {s}
            </a>
          </li>
        ))}
      </ul>
      {row.status !== "retired" && (
        <div className="row section-actions">
          {row.status === "pending" && (
            <button type="button" className="btn btn--small btn--primary" onClick={() => onAction({ kind: "approve", row })}>
              Approve
            </button>
          )}
          <button type="button" className="btn btn--small" onClick={() => onAction({ kind: "edit", row })}>
            Edit summary
          </button>
          <button type="button" className="btn btn--small btn--danger-outline" onClick={() => onAction({ kind: "retire", row })}>
            Retire
          </button>
        </div>
      )}
    </article>
  );
}

/**
 * AP-3: auto-generated company profiles (AP-1) wait here for review. Only approved ones reach an
 * interviewer brief. Approve, edit the summary or retire; each action is audited with a reason.
 */
export function AutoProfilesPage() {
  const [filter, setFilter] = useState<AutoProfileFilter>("pending");
  const list = useAutoProfiles(filter);
  const approve = useAutoProfileAction(part1Api.approve);
  const edit = useAutoProfileAction(part1Api.editSummary);
  const retire = useAutoProfileAction(part1Api.retire);
  const [pending, setPending] = useState<Pending | null>(null);
  const [draft, setDraft] = useState("");

  const open = (p: Pending) => {
    approve.reset();
    edit.reset();
    retire.reset();
    setDraft(p.row.summary);
    setPending(p);
  };
  const close = () => setPending(null);
  const mutation = pending?.kind === "approve" ? approve : pending?.kind === "edit" ? edit : retire;
  const counts = list.data?.counts;

  return (
    <>
      <PageHead title="Auto-profiles">
        <p>
          Short company profiles the app builds from the job posting's domain when a company is not in the curated
          list. Only approved profiles reach an interviewer brief, labeled "auto-generated".
        </p>
      </PageHead>
      <div className="segmented" role="group" aria-label="Status">
        {FILTERS.map((f) => (
          <button key={f.key} type="button" className="btn btn--small" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
            {counts && f.key !== "all" ? ` (${counts[f.key] ?? 0})` : ""}
          </button>
        ))}
      </div>

      {list.isPending && <Loading label="Loading auto-profiles" />}
      {list.isError && <ErrorNotice error={list.error} />}
      {list.data &&
        (list.data.profiles.length === 0 ? (
          <p className="section">{filter === "pending" ? "Nothing waits for review." : "No profiles here."}</p>
        ) : (
          list.data.profiles.map((row) => <ProfileCard key={row.id} row={row} onAction={open} />)
        ))}

      {pending && (
        <ReasonDialog
          title={
            pending.kind === "approve"
              ? `Approve ${pending.row.company_name}`
              : pending.kind === "edit"
                ? `Edit ${pending.row.company_name}`
                : `Retire ${pending.row.company_name}`
          }
          confirmLabel={pending.kind === "approve" ? "Approve" : pending.kind === "edit" ? "Save summary" : "Retire"}
          danger={pending.kind === "retire"}
          disabled={pending.kind === "edit" && (draft.trim() === "" || draft.trim() === pending.row.summary)}
          pending={mutation.isPending}
          error={mutation.isError ? mutation.error : undefined}
          onCancel={close}
          onConfirm={(reason) => {
            const id = pending.row.id;
            const done = { onSuccess: close };
            if (pending.kind === "approve") approve.mutate({ id, reason }, done);
            else if (pending.kind === "edit") edit.mutate({ id, reason, summary: draft.trim() }, done);
            else retire.mutate({ id, reason }, done);
          }}
        >
          {pending.kind === "approve" && <p>Briefs for {pending.row.company_name} will include this summary.</p>}
          {pending.kind === "edit" && <SummaryField value={draft} onChange={setDraft} />}
          {pending.kind === "retire" && (
            <p>
              {pending.row.company_name}'s profile stops reaching briefs. A retired profile cannot be approved again.
            </p>
          )}
        </ReasonDialog>
      )}
    </>
  );
}
