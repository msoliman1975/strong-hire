import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { jobsApi, type CreateJobRequest } from "../../api/planned";
import { ErrorNotice, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";

export const MIN_POSTING_CHARS = 100;

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

export function NewJobPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: CreateJobRequest) => jobsApi.create(body),
    onSuccess: (job) => navigate(`/jobs/${job.id}/confirm`),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const problem = validateJobInput(url, text);
    setError(problem);
    if (problem) return;
    create.mutate(url.trim() ? { source_url: url.trim() } : { raw_text: text.trim() });
  };

  return (
    <div className="page--narrow">
      <Steps current={0} steps={ONBOARDING_STEPS} />
      <PageHead title="Add a job posting">
        <p>Use the posting for the real job you are interviewing for. We read the company, title, level and requirements.</p>
      </PageHead>
      <form className="panel" onSubmit={onSubmit} noValidate>
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
        {create.isError && <ErrorNotice error={create.error} />}
        <div className="row section">
          <button type="submit" className="btn" disabled={create.isPending}>
            Read job posting
          </button>
        </div>
      </form>
    </div>
  );
}
