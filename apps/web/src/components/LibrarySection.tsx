import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { keys, useJobs, useResumes } from "../api/hooks";
import { jobTargetsApi, resumesApi } from "../api/inputs";
import { formatDate } from "../labels";
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
}

interface Props {
  kind: "job" | "cv";
  title: string;
  items: Item[] | undefined;
  loading: boolean;
  error: unknown;
  rename: (id: string, name: string) => Promise<unknown>;
  remove: (id: string) => Promise<void>;
  onChanged: () => void;
}

const WORDS = {
  job: { thing: "job", deleted: "job description", empty: "You have no saved jobs." },
  cv: { thing: "CV", deleted: "CV and its file", empty: "You have no saved CVs." },
};

function Library({ kind, title, items, loading, error, rename, remove, onChanged }: Props) {
  const words = WORDS[kind];
  const headingId = `library-${kind}-heading`;
  const dialog = useRef<HTMLDialogElement>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Item | null>(null);

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
      {loading && <Loading />}
      {error ? <ErrorNotice error={error} /> : null}
      {items && items.length === 0 && <p className="muted">{words.empty}</p>}
      {items && items.length > 0 && (
        <ul className="plain-list">
          {items.map((item) => (
            <li key={item.id}>
              {editing?.id === item.id ? (
                <form className="row" onSubmit={onRename} noValidate aria-label={`Rename ${item.name ?? words.thing}`}>
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
                <div className="row row--between">
                  <span>
                    {item.name ?? words.thing} <span className="muted">added {formatDate(item.addedAt)}</span>
                  </span>
                  <span className="row">
                    <button
                      type="button"
                      className="btn btn--quiet"
                      aria-label={`Rename ${item.name ?? words.thing}`}
                      onClick={() => {
                        setNameError(null);
                        setEditing({ id: item.id, value: item.name ?? "" });
                      }}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      className="btn btn--quiet"
                      aria-label={`Delete ${item.name ?? words.thing}`}
                      onClick={() => {
                        setToDelete(item);
                        openDialog(dialog.current);
                      }}
                    >
                      Delete
                    </button>
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {del.isError && <ErrorNotice error={del.error} title="The delete did not work" />}

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

/** R1: the Account page's "Saved jobs" and "Saved CVs", with rename and delete. */
export function SavedLibrary() {
  const jobs = useJobs();
  const resumes = useResumes();
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: keys.jobs });
    void queryClient.invalidateQueries({ queryKey: keys.resumes });
    void queryClient.invalidateQueries({ queryKey: keys.reports });
  };
  return (
    <>
      <Library
        kind="job"
        title="Saved jobs"
        items={jobs.data?.map((s) => ({
          id: s.job_target.id,
          name: s.job_target.name,
          addedAt: s.job_target.created_at,
        }))}
        loading={jobs.isPending}
        error={jobs.error}
        rename={jobTargetsApi.rename}
        remove={jobTargetsApi.remove}
        onChanged={refresh}
      />
      <Library
        kind="cv"
        title="Saved CVs"
        items={resumes.data?.map((r) => ({ id: r.id, name: r.name, addedAt: r.uploaded_at }))}
        loading={resumes.isPending}
        error={resumes.error}
        rename={resumesApi.rename}
        remove={resumesApi.remove}
        onChanged={refresh}
      />
    </>
  );
}
