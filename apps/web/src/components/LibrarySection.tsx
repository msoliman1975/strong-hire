import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import { keys, useJobs, useResumes } from "../api/hooks";
import { jobTargetsApi, resumesApi } from "../api/inputs";
import { formatDate } from "../labels";
import { resumeCheckPath } from "../paths";
import { checkedLabel, issueSummary, resumeIssueCounts } from "../pages/onboarding/resumeSummary";
import { useFeature } from "../theme/features";
import { ErrorNotice, Loading } from "./ui";

/** The API rejects names that are empty or longer than this (R1). */
export const NAME_MAX = 120;

// jsdom (Vitest) has no showModal(); the attribute fallback keeps the dialog testable.
const openDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.showModal === "function" ? d.showModal() : d.setAttribute("open", ""));
const closeDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.close === "function" ? d.close() : d.removeAttribute("open"));

/** Form validation only: trimmed, not empty, at most 120 characters. */
export function validateName(name: string): string | null {
  const value = name.trim();
  if (!value) return "Enter a name.";
  if (value.length > NAME_MAX) return `Use at most ${NAME_MAX} characters.`;
  return null;
}

interface Item {
  id: string;
  name: string | null;
  addedAt: string;
  /** LB-2: the item has reports, so it is archived instead of deleted. */
  inUse?: boolean;
  archivedAt?: string | null;
  /** Extra text after the date, for example the number of sessions. */
  detail?: string;
  /** IN-12 (v2 CVs): the breakdown page. The row opens it, and "Open breakdown" is its main action. */
  to?: string;
  /** IN-12: a second line, for example "Checked Oct 28 · 3 to fix · 1 accepted · 0 high". */
  summary?: string;
}

interface Props {
  kind: "job" | "cv";
  title: string;
  items: Item[] | undefined;
  loading: boolean;
  error: unknown;
  rename: (id: string, name: string) => Promise<unknown>;
  remove: (id: string) => Promise<void>;
  /** LB-2: given for job descriptions only. */
  archive?: (id: string) => Promise<unknown>;
  restore?: (id: string) => Promise<unknown>;
  onChanged: () => void;
  /** Shown under the heading, for example the "Show archived" switch. */
  toolbar?: ReactNode;
  empty?: ReactNode;
}

const WORDS = {
  job: { thing: "job description", deleted: "job description", empty: "You have no saved job descriptions." },
  cv: { thing: "CV", deleted: "CV and its file", empty: "You have no saved CVs." },
  /** NV-2: the v2 wording for the same list. */
  resume: { thing: "resume", deleted: "resume and its file", empty: "You have no saved resumes." },
};

/** R1 library list with rename and delete; LB-2 archive and restore for job descriptions. */
export function Library({
  kind,
  title,
  items,
  loading,
  error,
  rename,
  remove,
  archive,
  restore,
  onChanged,
  toolbar,
  empty,
}: Props) {
  const v2 = useFeature("v2_enabled");
  const words = WORDS[kind === "cv" && v2 ? "resume" : kind];
  const headingId = `library-${kind}-heading`;
  const dialog = useRef<HTMLDialogElement>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Item | null>(null);
  const navigate = useNavigate();
  // A click anywhere on a linked row opens it, except on its own links, buttons and fields.
  const openRow = (e: MouseEvent, to: string | undefined) => {
    if (!to || (e.target as HTMLElement).closest("a, button, input, select, textarea, label, form")) return;
    navigate(to);
  };

  const save = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => rename(id, name),
    onSuccess: () => {
      setEditing(null);
      onChanged();
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => remove(id),
    onSuccess: () => {
      setToDelete(null);
      onChanged();
    },
  });
  const shelve = useMutation({
    mutationFn: ({ id, back }: { id: string; back: boolean }) =>
      (back ? restore : archive)?.(id) ?? Promise.resolve(),
    onSuccess: onChanged,
  });

  const onRename = (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const problem = validateName(editing.value);
    setNameError(problem);
    if (!problem) save.mutate({ id: editing.id, name: editing.value.trim() });
  };

  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      {toolbar}
      {loading && <Loading />}
      {error ? <ErrorNotice error={error} /> : null}
      {items && items.length === 0 && (empty ?? <p className="muted">{words.empty}</p>)}
      {items && items.length > 0 && (
        <ul className="plain-list" aria-label={title}>
          {items.map((item) => {
            const label = item.name ?? words.thing;
            const archived = Boolean(item.archivedAt);
            return (
              <li key={item.id}>
                {editing?.id === item.id ? (
                  <form className="row" onSubmit={onRename} noValidate aria-label={`Rename ${label}`}>
                    <label className="visually-hidden" htmlFor={`rename-${item.id}`}>
                      New name
                    </label>
                    <input
                      id={`rename-${item.id}`}
                      type="text"
                      value={editing.value}
                      maxLength={NAME_MAX + 20}
                      onChange={(e) => setEditing({ id: item.id, value: e.target.value })}
                    />
                    <button type="submit" className="btn" disabled={save.isPending}>
                      Save name
                    </button>
                    <button type="button" className="btn btn--quiet" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                    {nameError && (
                      <p className="field-error" role="alert">
                        {nameError}
                      </p>
                    )}
                    {save.isError && <ErrorNotice error={save.error} />}
                  </form>
                ) : (
                  <div
                    className={`row row--between${item.to ? " library-row--link" : ""}`}
                    onClick={(e) => openRow(e, item.to)}
                  >
                    <span className={item.to ? "library-row__text" : undefined}>
                      {item.to ? (
                        <Link className="library-row__name" to={item.to}>
                          {label}
                        </Link>
                      ) : (
                        label
                      )}{" "}
                      {archived && <span className="chip">Archived</span>}{" "}
                      <span className="muted">
                        added {formatDate(item.addedAt)}
                        {item.detail ? `, ${item.detail}` : ""}
                      </span>
                      {item.summary && <span className="muted small library-row__summary">{item.summary}</span>}
                    </span>
                    <span className="row">
                      {item.to && (
                        <Link className="btn" to={item.to} aria-label={`Open breakdown for ${label}`}>
                          Open breakdown
                        </Link>
                      )}
                      {!archived && (
                        <button
                          type="button"
                          className="btn btn--quiet"
                          aria-label={`Rename ${label}`}
                          onClick={() => {
                            setNameError(null);
                            setEditing({ id: item.id, value: item.name ?? "" });
                          }}
                        >
                          Rename
                        </button>
                      )}
                      {archived && restore ? (
                        <button
                          type="button"
                          className="btn btn--quiet"
                          aria-label={`Restore ${label}`}
                          disabled={shelve.isPending}
                          onClick={() => shelve.mutate({ id: item.id, back: true })}
                        >
                          Restore
                        </button>
                      ) : item.inUse && archive ? (
                        <button
                          type="button"
                          className="btn btn--quiet"
                          aria-label={`Archive ${label}`}
                          title="It has reports, so it is archived instead of deleted."
                          disabled={shelve.isPending}
                          onClick={() => shelve.mutate({ id: item.id, back: false })}
                        >
                          Archive
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--quiet"
                          aria-label={`Delete ${label}`}
                          onClick={() => {
                            setToDelete(item);
                            openDialog(dialog.current);
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {del.isError && <ErrorNotice error={del.error} title="The delete did not work" />}
      {shelve.isError && <ErrorNotice error={shelve.error} />}
      <dialog ref={dialog} aria-labelledby={`${headingId}-confirm`} aria-describedby={`${headingId}-confirm-text`}>
        <h2 id={`${headingId}-confirm`}>Delete this {words.thing}?</h2>
        <p id={`${headingId}-confirm-text`}>
          We delete {toDelete?.name ?? `the ${words.thing}`}: the {words.deleted}. Your reports, interviews and
          progress are kept.
        </p>
        <div className="row row--end">
          <button type="button" className="btn btn--quiet" onClick={() => closeDialog(dialog.current)}>
            Keep it
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={del.isPending}
            onClick={() => {
              closeDialog(dialog.current);
              if (toDelete) del.mutate(toDelete.id);
            }}
          >
            Delete
          </button>
        </div>
      </dialog>
    </section>
  );
}

/** Refresh every list that shows library items after a change. */
export function useLibraryRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: keys.jobs });
    void queryClient.invalidateQueries({ queryKey: keys.resumes });
    void queryClient.invalidateQueries({ queryKey: keys.reports });
  };
}

/** LB-2: the saved job descriptions, with a "Show archived" switch. */
export function JobLibrary({ empty }: { empty?: ReactNode }) {
  const [showArchived, setShowArchived] = useState(false);
  const jobs = useJobs(showArchived);
  const refresh = useLibraryRefresh();
  return (
    <Library
      kind="job"
      title="Saved job descriptions"
      items={jobs.data?.map((s) => ({
        id: s.job_target.id,
        name: s.job_target.name,
        addedAt: s.job_target.created_at,
        inUse: s.in_use,
        archivedAt: s.job_target.archived_at,
        detail: `${s.sessions_count} ${s.sessions_count === 1 ? "session" : "sessions"}`,
      }))}
      loading={jobs.isPending}
      error={jobs.error}
      rename={jobTargetsApi.rename}
      remove={jobTargetsApi.remove}
      archive={jobTargetsApi.archive}
      restore={jobTargetsApi.restore}
      onChanged={refresh}
      empty={empty}
      toolbar={
        <label className="check">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      }
    />
  );
}

/**
 * LB-1: the saved CVs. v2 (IN-12): each row opens its breakdown and shows its state and issue counts,
 * worked out from the saved CV with the check page's rules.
 */
export function CvLibrary() {
  const resumes = useResumes();
  const refresh = useLibraryRefresh();
  const v2 = useFeature("v2_enabled");
  return (
    <Library
      kind="cv"
      title={v2 ? "Saved resumes" : "Saved CVs"}
      items={resumes.data?.map((r) => {
        if (!v2 || r.status === "pending") {
          return {
            id: r.id,
            name: r.name,
            addedAt: r.uploaded_at,
            detail: r.status === "pending" ? "reading the file" : r.confirmed_at ? undefined : "not checked yet",
          };
        }
        const counts = resumeIssueCounts(r);
        return {
          id: r.id,
          name: r.name,
          addedAt: r.uploaded_at,
          to: resumeCheckPath(r.id),
          summary: [checkedLabel(r), counts && issueSummary(counts)].filter(Boolean).join(" · "),
        };
      })}
      loading={resumes.isPending}
      error={resumes.error}
      rename={resumesApi.rename}
      remove={resumesApi.remove}
      onChanged={refresh}
    />
  );
}
