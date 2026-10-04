import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { keys, useResume, useResumes } from "../../api/hooks";
import { jobsApi, resumesApi, type ResumeRecord } from "../../api/planned";
import { ErrorNotice, Loading, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";
import { formatDate } from "../../labels";

export const MAX_RESUME_BYTES = 10 * 1024 * 1024;
const ACCEPTED = [".pdf", ".docx"];

/** Form validation only: a PDF or DOCX under 10 MB, or pasted text. */
export function validateResumeInput(file: File | null, text: string): string | null {
  if (!file && !text.trim()) return "Choose a PDF or DOCX file, or paste your resume text.";
  if (file) {
    const name = file.name.toLowerCase();
    if (!ACCEPTED.some((ext) => name.endsWith(ext))) return "The file must be a PDF or DOCX.";
    if (file.size > MAX_RESUME_BYTES) return "The file is larger than 10 MB.";
  }
  return null;
}

export function ResumePage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const existing = useResumes();
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const uploaded = useResume(uploadedId);

  const chooseResume = useMutation({
    mutationFn: (resumeId: string) => jobsApi.setResume(jobId, resumeId),
    onSuccess: (job) => {
      queryClient.setQueryData(keys.job(jobId), job);
      navigate(`/jobs/${jobId}/context`);
    },
  });

  const ready = (existing.data ?? []).filter((r) => r.status === "ready");

  return (
    <div className="page--narrow">
      <Steps current={1} steps={ONBOARDING_STEPS} />
      <PageHead title="Add your resume">
        <p>We compare your resume with the job to find your strengths and gaps.</p>
      </PageHead>

      {ready.length > 0 && !uploadedId && (
        <section className="panel" aria-labelledby="existing-heading">
          <h2 id="existing-heading">Use a resume you added before</h2>
          <ul className="plain-list">
            {ready.map((r) => (
              <li key={r.id} className="row row--between">
                <span>
                  {r.file_name ?? "Pasted text"} <span className="muted">added {formatDate(r.uploaded_at)}</span>
                </span>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => chooseResume.mutate(r.id)}
                  disabled={chooseResume.isPending}
                >
                  Use this resume
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {uploadedId ? (
        <section className="panel" aria-labelledby="parsed-heading">
          <h2 id="parsed-heading">Your resume</h2>
          {uploaded.isError && <ErrorNotice error={uploaded.error} />}
          {(uploaded.isPending || uploaded.data?.status === "parsing") && (
            <Loading label="Reading your resume. This takes up to a minute." />
          )}
          {uploaded.data?.status === "failed" && (
            <ErrorNotice error={uploaded.data.error ?? "We could not read this resume. Try pasting the text."} />
          )}
          {uploaded.data?.status === "ready" && <ParsedResume record={uploaded.data} />}
          <div className="row section">
            <button
              type="button"
              className="btn"
              disabled={uploaded.data?.status !== "ready" || chooseResume.isPending}
              onClick={() => chooseResume.mutate(uploadedId)}
            >
              Continue
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => setUploadedId(null)}>
              Upload a different resume
            </button>
          </div>
          {chooseResume.isError && <ErrorNotice error={chooseResume.error} />}
        </section>
      ) : (
        <UploadForm onUploaded={(r) => setUploadedId(r.id)} />
      )}
    </div>
  );
}

function UploadForm({ onUploaded }: { onUploaded: (r: ResumeRecord) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const upload = useMutation({ mutationFn: resumesApi.upload, onSuccess: onUploaded });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const problem = validateResumeInput(file, text);
    setError(problem);
    if (problem) return;
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("text", text.trim());
    upload.mutate(form);
  };

  return (
    <form className="panel" onSubmit={onSubmit} noValidate aria-labelledby="upload-heading">
      <h2 id="upload-heading">Upload a new resume</h2>
      <div className="field">
        <label htmlFor="resume-file">Resume file</label>
        <p className="hint" id="resume-file-hint">
          PDF or DOCX, up to 10 MB. We store the file encrypted, and you can delete it at any time.
        </p>
        <input
          id="resume-file"
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          aria-describedby="resume-file-hint"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
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
      {upload.isError && <ErrorNotice error={upload.error} />}
      <button type="submit" className="btn" disabled={upload.isPending}>
        Upload resume
      </button>
    </form>
  );
}

function ParsedResume({ record }: { record: ResumeRecord }) {
  const parsed = record.parsed;
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
