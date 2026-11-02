/**
 * RM-1 (mockup #cvs): "{First name}'s Resumes". One list, one row per resume, the main one marked.
 * Each row has its roles, open issues, story ideas, date added and check state (IN-12), and every
 * action: Open, Open breakdown, Make default (RM-2; "default" in the UI, `is_main` in the API), and Rename or Delete in the row's "More" menu (R1).
 * RMAP-2: this replaces the second "Saved resumes" list that the page used to fold below.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { resumesApi } from "../../api/inputs";
import { rolesApi } from "../../api/roles";
import { useAuth, useResumes, useStoryIdeas } from "../../api/hooks";
import type { ResumeOut, RoleOut } from "../../api/types";
import { resumesLabel } from "../../components/Layout";
import { NAME_MAX, useLibraryRefresh, validateName } from "../../components/LibrarySection";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { formatDate } from "../../labels";
import { MAX_RESUME_MB, MAX_RESUMES, RESUMES_FULL } from "../../limits";
import { resumeCheckPath } from "../../paths";
import { editedLabel, issuesOpen, resumeIssueCounts } from "../onboarding/resumeSummary";
import { START } from "../start/paths";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
 * "10 issues open · 2 high · 1 accepted", worked out with the same rules as the breakdown (IN-12),
 * so the list and the breakdown always agree.
 */
function issueFacts(resume: ResumeOut): string | null {
  const counts = resumeIssueCounts(resume);
  if (!counts) return null;
  return [
    issuesOpen(counts.open),
    counts.high > 0 ? `${counts.high} high` : null,
    counts.accepted > 0 ? `${counts.accepted} accepted` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function ResumeRow({ resume, roles }: { resume: ResumeOut; roles: RoleOut[] | undefined }) {
  const ready = resume.status === "extracted";
  const label = resume.name ?? "Resume";
  const ideas = useStoryIdeas(ready ? resume.id : null);
  const queryClient = useQueryClient();
  const refresh = useLibraryRefresh();
  const menu = useRef<HTMLDetailsElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
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

  const closeMenu = () => menu.current?.removeAttribute("open");
  // The More menu closes on a click outside it and on Escape, like any menu.
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && menu.current?.open) {
        closeMenu();
        menu.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  const onRename = (e: FormEvent) => {
    e.preventDefault();
    if (editing === null) return;
    const problem = validateName(editing);
    setNameError(problem);
    if (!problem) rename.mutate(editing.trim());
  };

  const facts = !ready
    ? ["Still being read"]
    : [usedBy(roles, resume.id), issueFacts(resume), ideas.data ? plural(ideas.data.ideas.length, "story idea") : null].filter(
        Boolean,
      );
  const dates = [`Added ${formatDate(resume.uploaded_at)}`, ready ? editedLabel(resume) : null].filter(Boolean);

  return (
    <li className="sx-list-row" data-testid="resume-row">
      {editing !== null ? (
        <form className="sx-row" onSubmit={onRename} noValidate aria-label={`Rename ${label}`} style={{ flex: 1 }}>
          <label className="visually-hidden" htmlFor={`rename-${resume.id}`}>
            New name
          </label>
          <input
            id={`rename-${resume.id}`}
            type="text"
            value={editing}
            maxLength={NAME_MAX + 20}
            onChange={(e) => setEditing(e.target.value)}
            autoFocus
          />
          <button type="submit" className="sx-btn sm" disabled={rename.isPending}>
            Save name
          </button>
          <button type="button" className="sx-btn quiet sm" onClick={() => setEditing(null)}>
            Cancel
          </button>
          {nameError && (
            <p className="field-error" role="alert">
              {nameError}
            </p>
          )}
          {rename.isError && <ErrorNotice error={rename.error} />}
        </form>
      ) : (
        <>
          <div className="sx-stack" style={{ gap: 2, minWidth: 0 }}>
            <strong>
              <Link className="sx-plain" to={resumePath(resume.id)}>
                {label}
              </Link>{" "}
              {resume.is_main && <span className="sx-chip dark">Default</span>}
            </strong>
            <span className="sx-small sx-muted">{facts.join(" · ")}</span>
            <span className="sx-small sx-muted">{dates.join(" · ")}</span>
          </div>
          <span className="sx-row">
            {!resume.is_main && (
              <button
                type="button"
                className="sx-btn quiet sm"
                onClick={() => makeMain.mutate()}
                disabled={makeMain.isPending}
              >
                Make default
              </button>
            )}
            {ready && (
              <Link className="sx-btn ghost sm" to={resumeCheckPath(resume.id)} aria-label={`Open breakdown for ${label}`}>
                Open breakdown
              </Link>
            )}
            <Link className="sx-btn sm" to={resumePath(resume.id)} aria-label={`Open ${label}`}>
              Open
            </Link>
            <details className="sx-menu" ref={menu}>
              <summary className="sx-btn quiet sm" aria-label={`More actions for ${label}`}>
                More ▾
              </summary>
              <div className="sx-menu__list" role="group" aria-label={`More actions for ${label}`}>
                <button
                  type="button"
                  aria-label={`Rename ${label}`}
                  onClick={() => {
                    closeMenu();
                    setNameError(null);
                    setEditing(resume.name ?? "");
                  }}
                >
                  Rename
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${label}`}
                  onClick={() => {
                    closeMenu();
                    remove.reset();
                    const d = dialog.current;
                    if (d && typeof d.showModal === "function") d.showModal();
                    else d?.setAttribute("open", "");
                  }}
                >
                  Delete
                </button>
              </div>
            </details>
          </span>
          {makeMain.isError && <ErrorNotice error={makeMain.error} />}
        </>
      )}
      <dialog ref={dialog} aria-labelledby={`delete-${resume.id}`} className="sx-dialog">
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
            <button
              type="button"
              className="sx-btn quiet sm"
              onClick={() => {
                dialog.current?.close?.();
                dialog.current?.removeAttribute("open");
              }}
            >
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
      {resumes.data && (
        <div className="sx-card">
          {live.length === 0 ? (
            <p className="sx-muted">No resume yet. Add one and Strova reads it.</p>
          ) : (
            <ul className="sx-rows" aria-label="Your resumes">
              {live.map((r) => (
                <ResumeRow key={r.id} resume={r} roles={roles.data} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
