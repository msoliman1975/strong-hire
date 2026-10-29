import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { useResume, useResumes, useResumeTask } from "../../api/hooks";
import { jobProblem, resumesApi, sha256Hex } from "../../api/inputs";
import type { ResumeAccepted, ResumeOut } from "../../api/types";
import { ErrorNotice, Loading, PageHead, Steps } from "../../components/ui";
import { formatDate } from "../../labels";
import { friendlyLimitError, MAX_RESUME_BYTES_V2, MAX_RESUME_MB, MAX_RESUMES, RESUME_TOO_BIG, RESUMES_FULL } from "../../limits";
import { checkPath, rehearsalPath } from "../../paths";
import { useFeature } from "../../theme/features";
import { onboardingLinks, STEP_NOTES, useOnboardingSteps } from "./steps";

/** The API accepts files up to 5 MB. */
export const MAX_RESUME_BYTES = 5 * 1024 * 1024;
const ACCEPTED = [".pdf", ".docx"];

/** Form validation only: a PDF or DOCX up to 5 MB (v2: 1 MB), or pasted text. */
export function validateResumeInput(file: File | null, text: string, maxBytes = MAX_RESUME_BYTES): string | null {
  if (!file && !text.trim()) return "Choose a PDF or DOCX file, or paste your resume text.";
  if (file) {
    const name = file.name.toLowerCase();
    if (!ACCEPTED.some((ext) => name.endsWith(ext))) return "The file must be a PDF or DOCX.";
    if (file.size > maxBytes) return maxBytes === MAX_RESUME_BYTES ? "The file is larger than 5 MB." : RESUME_TOO_BIG;
  }
  return null;
}

export function ResumePage() {
  const steps = useOnboardingSteps();
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const existing = useResumes();
  const [upload, setUpload] = useState<{ id: string; task: string | null } | null>(null);
  const task = useResumeTask(upload?.id ?? null, upload?.task ?? null);
  const problem = jobProblem(task.data);
  const uploaded = useResume(upload?.id ?? null, problem === null);

  const ready = (existing.data ?? []).filter((r) => r.status === "extracted");
  // A CV the user has not checked yet goes to "Check your CV" first. A confirmed one goes to the
  // rehearsal page, which shows the earlier reports for this job and CV, or starts the gap analysis (PR-3).
  const choose = (saved: ResumeOut) =>
    navigate(saved.confirmed_at ? rehearsalPath(jobId, saved.id) : checkPath(jobId, saved.id));

  return (
    <div className="page--narrow">
      <Steps current={1} steps={steps} links={onboardingLinks(jobId)} note={STEP_NOTES.resume} />
      <PageHead title="Choose a resume">
        <p>Pick a resume you saved, or upload a new one. We save it for next time. We compare it with the job to find your strengths and gaps.</p>
      </PageHead>

      {ready.length > 0 && !upload && (
        <section className="panel" aria-labelledby="existing-heading">
          <h2 id="existing-heading">Use a resume you saved</h2>
          <p className="muted">We do not read a saved resume again.</p>
          <ul className="plain-list">
            {ready.map((r) => (
              <li key={r.id} className="row row--between">
                <span>
                  {r.name ?? (r.has_file ? "Uploaded file" : "Pasted text")}{" "}
                  <span className="muted">added {formatDate(r.uploaded_at)}</span>
                </span>
                <button type="button" className="btn btn--secondary" onClick={() => choose(r)}>
                  Use this resume
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {upload ? (
        <section className="panel" aria-labelledby="parsed-heading">
          <h2 id="parsed-heading">Your resume</h2>
          {uploaded.isError && <ErrorNotice error={uploaded.error} />}
          {task.isError && <ErrorNotice error={task.error} />}
          {problem && (
            <ErrorNotice error={problem.refused ? problem.message : `${problem.message} Try pasting the text instead.`} />
          )}
          {!problem && (uploaded.isPending || uploaded.data?.status === "pending") && (
            <Loading label="Reading your resume. This takes up to a minute." />
          )}
          {uploaded.data?.status === "extracted" && <ParsedResume record={uploaded.data} />}
          <div className="row section">
            <button
              type="button"
              className="btn"
              disabled={uploaded.data?.status !== "extracted"}
              onClick={() => navigate(checkPath(jobId, upload.id))}
            >
              Check and continue
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => setUpload(null)}>
              Upload a different resume
            </button>
          </div>
        </section>
      ) : (
        <UploadForm
          onUploaded={(r) => setUpload({ id: r.resume.id, task: r.job?.id ?? null })}
          onUseSaved={choose}
        />
      )}
    </div>
  );
}

export function UploadForm({
  onUploaded,
  onUseSaved,
}: {
  onUploaded: (r: ResumeAccepted) => void;
  onUseSaved: (saved: ResumeOut) => void;
}) {
  // v2 (R3): 1 MB per file and 5 resumes on file, as the API enforces them.
  const v2 = useFeature("v2_enabled");
  const resumes = useResumes();
  const onFile = (resumes.data ?? []).filter((r) => !r.deleted).length;
  const full = v2 && onFile >= MAX_RESUMES;
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [offer, setOffer] = useState<{ saved: ResumeOut; form: FormData } | null>(null);
  const upload = useMutation({ mutationFn: resumesApi.upload, onSuccess: onUploaded });
  // R1: the same file (or text) saved before is offered instead of reading it again.
  const check = useMutation({
    mutationFn: async (form: FormData) => {
      const sent = form.get("file");
      const hash = await sha256Hex(sent instanceof File ? await sent.arrayBuffer() : String(form.get("text") ?? ""));
      return (await resumesApi.match(hash)).resume;
    },
    onSuccess: (saved, form) => {
      if (saved) setOffer({ saved, form });
      else upload.mutate(form);
    },
    // The check only saves work. If it fails, upload as before.
    onError: (_err, form) => upload.mutate(form),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const problem = full ? RESUMES_FULL : validateResumeInput(file, text, v2 ? MAX_RESUME_BYTES_V2 : MAX_RESUME_BYTES);
    setError(problem);
    if (problem) return;
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("text", text.trim());
    setOffer(null);
    check.mutate(form);
  };

  return (
    <form className="panel" onSubmit={onSubmit} noValidate aria-labelledby="upload-heading">
      <h2 id="upload-heading">Upload a new resume</h2>
      <div className="field">
        <label htmlFor="resume-file">Resume file</label>
        <p className="hint" id="resume-file-hint">
          {v2
            ? `PDF or DOCX, up to ${MAX_RESUME_MB} MB. You can keep ${MAX_RESUMES} resumes; you have ${onFile}.`
            : "PDF or DOCX, up to 5 MB."}{" "}
          We store the file encrypted, and you can delete it at any time.
        </p>
        <input
          id="resume-file"
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          aria-describedby="resume-file-hint"
          onChange={(e) => {
            const picked = e.target.files?.[0] ?? null;
            setFile(picked);
            // v2: say it at once when the file is too big, before any upload.
            setError(v2 && picked && picked.size > MAX_RESUME_BYTES_V2 ? RESUME_TOO_BIG : null);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="resume-text">Or paste your resume text</label>
        <textarea id="resume-text" rows={8} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {upload.isError && <ErrorNotice error={friendlyLimitError(upload.error)} />}
      {offer && (
        <div className="notice" role="status">
          <p>You saved this CV before as {offer.saved.name ?? "a saved CV"}. Use it?</p>
          <div className="row">
            <button type="button" className="btn" onClick={() => onUseSaved(offer.saved)}>
              Use the saved CV
            </button>
            <button
              type="button"
              className="btn btn--quiet"
              disabled={upload.isPending}
              onClick={() => {
                upload.mutate(offer.form);
                setOffer(null);
              }}
            >
              Upload it again
            </button>
          </div>
        </div>
      )}
      {full && (
        <p className="notice" role="status" data-testid="resumes-full">
          {RESUMES_FULL}
        </p>
      )}
      <button type="submit" className="btn" disabled={upload.isPending || check.isPending || full}>
        Upload resume
      </button>
    </form>
  );
}

function ParsedResume({ record }: { record: ResumeOut }) {
  const parsed = record.resume;
  if (!parsed) return null;
  return (
    <div className="stack">
      {parsed.summary && <p>{parsed.summary}</p>}
      <div>
        <h3>Roles</h3>
        <ul>
          {parsed.roles.map((role) => (
            <li key={`${role.company}-${role.title}-${role.start}`}>
              {role.title}, {role.company}{" "}
              <span className="muted">
                {role.start ?? "?"} to {role.end ?? "now"}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3>Skills</h3>
        <p>{parsed.skills.join(", ")}</p>
      </div>
    </div>
  );
}
