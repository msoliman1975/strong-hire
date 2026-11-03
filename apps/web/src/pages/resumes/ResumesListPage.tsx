/**
 * RM-1, RSD-1 to RSD-3 (mockup "Resumes list (2 columns)"): "{First name}'s Resumes". One card per
 * resume in two columns, the default one marked. Each card has three tiles (roles using it, open
 * issues, story ideas), "Added {date} · Edited {date}", and its actions in plain sight: Show details
 * (the check page), Set as default (RM-2; "default" in the UI, `is_main` in the API), Rename and
 * Delete (R1, RMAP-5). RMAP-2: this is the one resume list.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { resumesApi } from "../../api/inputs";
import { rolesApi } from "../../api/roles";
import { useAuth, useResumes, useStoryIdeas } from "../../api/hooks";
import type { ResumeOut, RoleOut } from "../../api/types";
import { resumesLabel } from "../../components/Layout";
import { NAME_MAX, useLibraryRefresh, validateName } from "../../components/LibrarySection";
import { ErrorNotice, Loading } from "../../components/ui";
import { AddCard, SummaryCard, type StatTileProps } from "../../components/ux/SummaryCard";
import "../../components/ux/ux.css";
import { formatDate } from "../../labels";
import { MAX_RESUME_MB, MAX_RESUMES, RESUMES_FULL } from "../../limits";
import { resumeCheckPath } from "../../paths";
import { editedLabel, resumeIssueCounts } from "../onboarding/resumeSummary";
import { START } from "../start/paths";

/** "1 slot left.", "2 slots left." */
const slotsLeft = (n: number) => `${n} ${n === 1 ? "slot" : "slots"} left.`;

export const resumePath = (id: string) => `/resumes/${id}`;

/** "a, b and c". */
const andList = (items: string[]) =>
  items.length === 1 ? items[0] : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;

/**
 * "Used by Stripe and Shopify": the companies of the roles whose interviews use this resume. A
 * company with two roles is named once, with its count: "Used by Rubrik (2 roles) and Sourcegraph".
 */
export function usedBy(roles: RoleOut[] | undefined, resumeId: string): string | null {
  if (!roles) return null;
  const names = usingCompanies(roles, resumeId);
  return names.length === 0 ? "Not used by a role" : `Used by ${andList(names)}`;
}

/** "Rubrik (2 roles)", "Sourcegraph": the roles whose interviews use this resume, by company. */
function usingCompanies(roles: RoleOut[], resumeId: string): string[] {
  const counts = new Map<string, number>();
  for (const r of roles) {
    if (!r.interviews.some((i) => i.interview.resume_id === resumeId)) continue;
    const name = r.role.company_name ?? r.role.name ?? "a role";
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts].map(([name, n]) => (n > 1 ? `${name} (${n} roles)` : name));
}

/**
 * RMAP-5: what the delete dialog says about the roles that use the resume. Delete is allowed; those
 * roles keep their takes and report and ask for another resume.
 */
export function deleteRolesNote(roles: RoleOut[] | undefined, resumeId: string): string | null {
  const names = roles ? usingCompanies(roles, resumeId) : [];
  if (names.length === 0) return null;
  const count = roles?.filter((r) => r.interviews.some((i) => i.interview.resume_id === resumeId)).length ?? 0;
  const keep = count === 1 ? "It keeps its takes and report, and asks" : "They keep their takes and reports, and each asks";
  return `${andList(names)} ${count === 1 ? "uses" : "use"} this resume. ${keep} you to pick another resume.`;
}

/**
 * RSD-1, D-4: how many roles use this resume: the roles with an interview on it, the rule behind
 * `usedBy`.
 */
export function usingRoleCount(roles: RoleOut[] | undefined, resumeId: string): number | null {
  if (!roles) return null;
  return roles.filter((r) => r.interviews.some((i) => i.interview.resume_id === resumeId)).length;
}

export const HIGH_MARK_LABEL = "Includes high-severity issues";

/**
 * RSD-1, RSD-2: the three tiles. Counts come from the same helpers as the check page (D-4):
 * `usingRoleCount`, `resumeIssueCounts` and the story-ideas query. "—" while a count loads.
 */
export function resumeStats(
  roleCount: number | null,
  issues: { open: number; high: number } | null,
  ideas: number | null,
): readonly [StatTileProps, StatTileProps, StatTileProps] {
  const word = (n: number | null, one: string, many: string) => (n === 1 ? one : many);
  return [
    { value: roleCount ?? "—", label: word(roleCount, "role", "roles") },
    issues && issues.high > 0
      ? { value: issues.open, label: word(issues.open, "open issue", "open issues"), tone: "warn", markLabel: HIGH_MARK_LABEL }
      : { value: issues?.open ?? "—", label: word(issues?.open ?? null, "open issue", "open issues") },
    { value: ideas ?? "—", label: word(ideas, "story idea", "story ideas") },
  ];
}

const ICONS = {
  star: "M8 2l1.8 3.8 4.2.5-3.1 2.9.8 4.1L8 11.3 4.3 13.3l.8-4.1L2 6.3l4.2-.5z",
  pencil: "M11 2.5l2.5 2.5L6 12.5H3.5V10z",
  trash: "M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.7 9h6.6l.7-9",
};

/** A small stroke icon for a footer button; the button's text and label carry the meaning. */
function Icon({ d }: { d: string }) {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={d} />
    </svg>
  );
}

function ResumeCard({ resume, roles }: { resume: ResumeOut; roles: RoleOut[] | undefined }) {
  const ready = resume.status === "extracted";
  const label = resume.name ?? "Resume";
  // RSD-16: one story-ideas request per card. There is no batched read without a backend change (D-8).
  const ideas = useStoryIdeas(ready ? resume.id : null);
  const queryClient = useQueryClient();
  const refresh = useLibraryRefresh();
  const dialog = useRef<HTMLDialogElement>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  const makeMain = useMutation({
    mutationFn: () => resumesApi.setMain(resume.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["resumes"] }),
  });
  const rename = useMutation({
    mutationFn: (name: string) => resumesApi.rename(resume.id, name),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => resumesApi.remove(resume.id),
    onSuccess: () => {
      dialog.current?.close?.();
      dialog.current?.removeAttribute("open");
      refresh();
      // Roles show which resume they use.
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
  });

  const onRename = (e: FormEvent) => {
    e.preventDefault();
    if (editing === null) return;
    const problem = validateName(editing);
    setNameError(problem);
    if (!problem) rename.mutate(editing.trim());
  };
  const closeDialog = () => {
    dialog.current?.close?.();
    dialog.current?.removeAttribute("open");
    deleteButton.current?.focus();
  };

  const counts = ready ? resumeIssueCounts(resume) : null;
  const stats = resumeStats(usingRoleCount(roles, resume.id), counts, ideas.data ? ideas.data.ideas.length : null);
  const meta = ready
    ? [`Added ${formatDate(resume.uploaded_at)}`, editedLabel(resume)].filter(Boolean).join(" · ")
    : "Strova is reading this resume. The numbers show when she is done.";
  const chip = resume.is_main ? (
    <span className="sx-chip dark">Default</span>
  ) : !ready ? (
    <span className="sx-chip v">Being read</span>
  ) : null;

  const renameButton = (
    <button
      type="button"
      className="sx-btn quiet sm"
      aria-label={`Rename ${label}`}
      onClick={() => {
        setNameError(null);
        setEditing(resume.name ?? "");
      }}
    >
      <Icon d={ICONS.pencil} />
      Rename
    </button>
  );
  const actions = (
    <>
      {ready && !resume.is_main && (
        <button
          type="button"
          className="sx-btn quiet sm"
          aria-label={`Set ${label} as default`}
          onClick={() => makeMain.mutate()}
          disabled={makeMain.isPending}
        >
          <Icon d={ICONS.star} />
          Set as default
        </button>
      )}
      {renameButton}
      <button
        ref={deleteButton}
        type="button"
        className="sx-btn quiet sm danger"
        aria-label={`Delete ${label}`}
        onClick={() => {
          remove.reset();
          const d = dialog.current;
          if (d && typeof d.showModal === "function") d.showModal();
          else d?.setAttribute("open", "");
        }}
      >
        <Icon d={ICONS.trash} />
        Delete
      </button>
    </>
  );

  return (
    <li data-testid="resume-row" style={{ display: "grid", listStyle: "none", minWidth: 0 }}>
      <SummaryCard
        title={label}
        chip={chip}
        stats={stats}
        loading={!ready}
        meta={editing === null ? meta : undefined}
        primary={
          ready && editing === null ? (
            <Link className="sx-btn sm" to={resumeCheckPath(resume.id)} aria-label={`Show details: ${label}`}>
              Show details
            </Link>
          ) : undefined
        }
        actions={editing === null ? actions : undefined}
      >
        {editing !== null && (
          <form className="sx-stack" onSubmit={onRename} noValidate aria-label={`Rename ${label}`}>
            <div className="sx-field">
              <label htmlFor={`rename-${resume.id}`}>New name</label>
              <input
                id={`rename-${resume.id}`}
                type="text"
                value={editing}
                maxLength={NAME_MAX + 20}
                onChange={(e) => setEditing(e.target.value)}
                autoFocus
              />
            </div>
            {nameError && (
              <p className="field-error" role="alert">
                {nameError}
              </p>
            )}
            {rename.isError && <ErrorNotice error={rename.error} />}
            <div className="sx-row">
              <button type="submit" className="sx-btn sm" disabled={rename.isPending}>
                Save name
              </button>
              <button type="button" className="sx-btn quiet sm" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {makeMain.isError && <ErrorNotice error={makeMain.error} />}
      </SummaryCard>
      <dialog ref={dialog} aria-labelledby={`delete-${resume.id}`} className="sx-dialog" onClose={() => deleteButton.current?.focus()}>
        <div className="sx-card">
          <h2 id={`delete-${resume.id}`}>Delete this resume?</h2>
          <p className="sx-small sx-muted">
            We delete {label} and its file. Your reports, interviews and progress are kept.
            {resume.is_main && " Your newest other resume becomes your default resume."}
          </p>
          {deleteRolesNote(roles, resume.id) && (
            <p className="sx-notice warn sx-small" data-testid="delete-roles-note">
              {deleteRolesNote(roles, resume.id)}
            </p>
          )}
          {remove.isError && <ErrorNotice error={remove.error} title="The delete did not work" />}
          <div className="sx-row">
            <button type="button" className="sx-btn sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
              Delete
            </button>
            <button type="button" className="sx-btn quiet sm" onClick={closeDialog}>
              Keep it
            </button>
          </div>
        </div>
      </dialog>
    </li>
  );
}

export function ResumesListPage() {
  const auth = useAuth();
  const resumes = useResumes();
  const roles = useQuery({ queryKey: ["roles"], queryFn: rolesApi.list });
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const full = live.length >= MAX_RESUMES;
  const title = resumesLabel(auth.data?.user?.full_name);
  return (
    <div className="sx-page">
      <div className="sx-between">
        <h1>{title}</h1>
        {full ? (
          <button type="button" className="sx-btn" disabled>
            Add a resume
          </button>
        ) : (
          <Link className="sx-btn" to={START}>
            Add a resume
          </Link>
        )}
      </div>
      <p className="sx-muted">
        Your default resume feeds your story ideas and is used for new target roles. Use other resumes for roles where you
        sent a different version.
      </p>
      {resumes.data && (
        <p className="sx-muted sx-small" data-testid="resume-limit">
          {live.length} of {MAX_RESUMES} · up to {MAX_RESUME_MB} MB each
        </p>
      )}
      {full && (
        <p className="sx-notice ground" role="status" data-testid="resumes-full">
          {RESUMES_FULL}
        </p>
      )}
      {resumes.isPending && <Loading label="Loading your resumes" />}
      {resumes.isError && <ErrorNotice error={resumes.error} />}
      {resumes.data && live.length === 0 && (
        <div className="sx-card dashed">
          <p className="sx-muted">No resume yet. Add one and Strova reads it.</p>
        </div>
      )}
      {resumes.data && live.length > 0 && (
        <div className="sx-grid2 stretch">
          {/* The list keeps its semantics; its items sit in the page grid (display: contents). */}
          <ul role="list" aria-label="Your resumes" style={{ display: "contents" }}>
            {live.map((r) => (
              <ResumeCard key={r.id} resume={r} roles={roles.data} />
            ))}
          </ul>
          {!full && (
            <AddCard
              to={START}
              title="Add a resume"
              hint={`${slotsLeft(MAX_RESUMES - live.length)} Add the version you sent for a role.`}
            />
          )}
        </div>
      )}
    </div>
  );
}
