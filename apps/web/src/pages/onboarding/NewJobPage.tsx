import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useJobs } from "../../api/hooks";
import { jobTargetsApi } from "../../api/inputs";
import type { JobTargetCreate, JobTargetOut } from "../../api/types";
import { ErrorNotice, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";
import { formatDate } from "../../labels";
import type { NewJobReturn } from "../../paths";

export const MIN_POSTING_CHARS = 100;

/** "library" when the user came from the Job descriptions page; else the rehearsal goes on. */
export function newJobReturn(value: string | null): NewJobReturn {
  return value === "library" ? "library" : "rehearsal";
}

/** Where the confirm page continues, with the background job to watch. */
export function confirmPath(jobId: string, taskId: string | null | undefined, then: NewJobReturn = "rehearsal"): string {
  const q = new URLSearchParams();
  if (taskId) q.set("task", taskId);
  if (then === "library") q.set("then", "library");
  const query = q.toString();
  return query ? `/jobs/${jobId}/confirm?${query}` : `/jobs/${jobId}/confirm`;
}

/** After the job details are confirmed: back to the Job descriptions page, or on to the resume step. */
export function afterConfirmPath(jobId: string, then: NewJobReturn): string {
  return then === "library" ? "/jobs" : `/jobs/${jobId}/resume`;
}

/** Form validation only: one of URL or text, a well-formed http(s) URL, enough text to read. */
export function validateJobInput(url: string, text: string): string | null {
  const u = url.trim();
  const t = text.trim();
  if (!u && !t) return "Paste the job posting link or the job posting text.";
  if (u) {
    try {
      const parsed = new URL(u);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("protocol");
    } catch {
      return "The link must start with http:// or https://.";
    }
  }
  if (!u && t.length < MIN_POSTING_CHARS) {
    return `The pasted text is too short. Paste the full posting (at least ${MIN_POSTING_CHARS} characters).`;
  }
  return null;
}

/** R1: a saved job is not read again. A read one goes on to the resume step, or back to the library. */
export function savedJobPath(job: JobTargetOut, then: NewJobReturn = "rehearsal"): string {
  return job.status === "extracted" ? afterConfirmPath(job.id, then) : confirmPath(job.id, null, then);
}

export function NewJobPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const then = newJobReturn(params.get("then"));
  const saved = useJobs();
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [offer, setOffer] = useState<{ job: JobTargetOut; body: JobTargetCreate } | null>(null);
  const create = useMutation({
    mutationFn: (body: JobTargetCreate) => jobTargetsApi.create(body),
    onSuccess: (accepted) => navigate(confirmPath(accepted.job_target.id, accepted.job?.id, then)),
  });
  // R1: before reading a posting, ask the API whether the user saved the same one before.
  const check = useMutation({
    mutationFn: (body: JobTargetCreate) => jobTargetsApi.match({ text: body.text, url: body.url }),
    onSuccess: (found, body) => {
      if (found.job_target) setOffer({ job: found.job_target, body });
      else create.mutate(body);
    },
    // The check only saves work. If it fails, read the posting as before.
    onError: (_err, body) => create.mutate(body),
  });
  const savedJobs = saved.data ?? [];
  // IN-1: some sites (LinkedIn) cannot be read. The API says so; the user pastes the text.
  const pasteRequired = create.error instanceof ApiError && create.error.code === "paste_required";

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const problem = pasteRequired && !text.trim() ? "Paste the job posting text." : validateJobInput(url, text);
    setError(problem);
    if (problem) return;
    // With both, the API reads the text and uses the link to match the company.
    setOffer(null);
    check.mutate({ url: url.trim() || null, text: text.trim() || null });
  };

  return (
    <div className="page--narrow">
      {then === "rehearsal" && <Steps current={0} steps={ONBOARDING_STEPS} />}
      <PageHead title="Add a job description">
        <p>
          A job description is the job posting for the real job you are interviewing for. Paste its link or its text.
          We read the company, title, level and requirements, and save it for your rehearsals.
        </p>
      </PageHead>
      {then === "rehearsal" && savedJobs.length > 0 && (
        <section className="panel" aria-labelledby="saved-jobs-heading">
          <h2 id="saved-jobs-heading">Use a job description you saved</h2>
          <p className="muted">We do not read a saved job description again.</p>
          <ul className="plain-list">
            {savedJobs.map(({ job_target: job }) => (
              <li key={job.id} className="row row--between">
                <span>
                  {job.name ?? "Job"} <span className="muted">added {formatDate(job.created_at)}</span>
                </span>
                <button type="button" className="btn btn--secondary" onClick={() => navigate(savedJobPath(job, then))}>
                  Use this job description
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <form className="panel" onSubmit={onSubmit} noValidate aria-labelledby="new-job-heading">
        <h2 id="new-job-heading">Add a new job description</h2>
        <div className="field">
          <label htmlFor="job-url">Job posting link</label>
          <p className="hint" id="job-url-hint">
            Greenhouse, Lever, Ashby, Workday and most career pages work. For LinkedIn, paste the text.
          </p>
          <input
            id="job-url"
            type="url"
            inputMode="url"
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-describedby="job-url-hint"
          />
        </div>
        <div className="field">
          <label htmlFor="job-text">Or paste the job posting text</label>
          <textarea id="job-text" value={text} onChange={(e) => setText(e.target.value)} rows={8} />
        </div>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {offer && (
          <div className="notice" role="status">
            <p>You saved this job description before as {offer.job.name ?? "a saved job description"}. Use it?</p>
            <div className="row">
              <button type="button" className="btn" onClick={() => navigate(savedJobPath(offer.job, then))}>
                Use the saved job description
              </button>
              <button
                type="button"
                className="btn btn--quiet"
                disabled={create.isPending}
                onClick={() => {
                  create.mutate(offer.body);
                  setOffer(null);
                }}
              >
                Read it again as a new job description
              </button>
            </div>
          </div>
        )}
        {pasteRequired ? (
          <div className="notice notice--error" role="alert">
            <p>This site does not allow automatic reading. Paste the job posting text above. We keep the link.</p>
          </div>
        ) : (
          create.isError && <ErrorNotice error={create.error} />
        )}
        <div className="row section">
          <button type="submit" className="btn" disabled={create.isPending || check.isPending}>
            Read job posting
          </button>
        </div>
      </form>
    </div>
  );
}
