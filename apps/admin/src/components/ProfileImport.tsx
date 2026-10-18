import { useId, useState } from "react";
import { Link } from "react-router";

import { importProblems, useImportProfile, type ProfileImportOut } from "../api/content";

/** The company_slug in pasted text, if the text is JSON with one. The API checks it again. */
function slugOf(text: string): string | null {
  try {
    const data = JSON.parse(text.replace(/^\uFEFF/, "")) as { company_slug?: unknown };
    return typeof data.company_slug === "string" && data.company_slug ? data.company_slug : null;
  } catch {
    return null;
  }
}

/**
 * AT-3: import a profile JSON from a file or pasted text. The API validates it with the same
 * code as `strongctl profiles validate` and lists every problem, or stores it as a Draft.
 * Without `slug` (the Companies page), the company comes from the file's company_slug.
 */
export function ProfileImport({ slug, onDone }: { slug?: string; onDone?: (out: ProfileImportOut) => void }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [createCompany, setCreateCompany] = useState(false);
  const [force, setForce] = useState(false);
  const [reason, setReason] = useState("");
  const save = useImportProfile();
  const ids = { file: useId(), text: useId(), reason: useId() };
  const problems = save.isError ? importProblems(save.error) : null;
  const target = slug ?? slugOf(text);

  return (
    <form
      className="panel import"
      aria-label="Import a profile"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          {
            // An unreadable file has no slug; the API still validates it and lists the problems.
            slug: target ?? "unknown",
            body: { profile_text: text, reason: reason.trim(), create_company: createCompany, force },
          },
          { onSuccess: (out) => onDone?.(out) },
        );
      }}
    >
      <h2>Import a profile</h2>
      <p className="muted">
        The file is checked against the company profile schema and stored as a Draft. Nothing changes for
        candidates until a version is published.
      </p>
      <div className="field">
        <label htmlFor={ids.file}>Profile JSON file</label>
        <input
          id={ids.file}
          type="file"
          accept=".json,application/json"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setFileName(file.name);
            setText(await file.text());
            save.reset();
          }}
        />
      </div>
      <div className="field">
        <label htmlFor={ids.text}>Or paste the JSON</label>
        <textarea
          id={ids.text}
          className="code-input"
          rows={8}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setFileName(null);
            save.reset();
          }}
        />
      </div>
      {fileName && <p className="muted">Read {fileName}.</p>}
      {!slug && text && <p className="muted">Company: {target ?? "unknown (the file has no company_slug)"}</p>}
      <div className="row">
        {!slug && (
          <label className="check">
            <input type="checkbox" checked={createCompany} onChange={(e) => setCreateCompany(e.target.checked)} />
            Add the company if it is new (inactive)
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Store it even if nothing changed
        </label>
      </div>
      <div className="field">
        <label htmlFor={ids.reason}>Reason (saved in the audit log)</label>
        <input id={ids.reason} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </div>
      <button
        type="submit"
        className="btn btn--primary"
        disabled={!text.trim() || reason.trim().length < 3 || save.isPending}
      >
        Validate and import
      </button>

      {save.isError && (
        <div className="notice notice--error" role="alert">
          <p className="label">{save.error.message}</p>
          {problems && (
            <ul className="problems">
              {problems.map((p) => (
                <li key={p}>
                  <code>{p}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {save.isSuccess && <ImportResult out={save.data} />}
    </form>
  );
}

function ImportResult({ out }: { out: ProfileImportOut }) {
  const { company, version, diff } = out;
  return (
    <div className="notice" role="status">
      <p className="label">
        Stored {company.slug} version {version.version} as Draft
        {out.company_created ? " and added the company (inactive)" : ""}.
      </p>
      <ul>
        {out.summary.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p>
        {diff.a === null ? "No published version yet." : `${diff.total} changed values against version ${diff.a}.`}{" "}
        <Link to={`/content/companies/${company.slug}`}>Open {company.name}</Link>
      </p>
    </div>
  );
}
