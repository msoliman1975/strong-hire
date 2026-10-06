import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { jobTargetsApi } from "../../api/inputs";
import type { JobTargetCreate } from "../../api/types";
import { ErrorNotice, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";

export const MIN_POSTING_CHARS = 100;

/** Where the confirm page continues, with the background job to watch. */
export function confirmPath(jobId: string, taskId: string | null | undefined): string {
  return taskId ? `/jobs/${jobId}/confirm?task=${encodeURIComponent(taskId)}` : `/jobs/${jobId}/confirm`;
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

export function NewJobPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: JobTargetCreate) => jobTargetsApi.create(body),
    onSuccess: (accepted) => navigate(confirmPath(accepted.job_target.id, accepted.job?.id)),
  });
  // IN-1: some sites (LinkedIn) cannot be read. The API says so; the user pastes the text.
  const pasteRequired = create.error instanceof ApiError && create.error.code === "paste_required";

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const problem = pasteRequired && !text.trim() ? "Paste the job posting text." : validateJobInput(url, text);
    setError(problem);
    if (problem) return;
    // With both, the API reads the text and uses the link to match the company.
    create.mutate({ url: url.trim() || null, text: text.trim() || null });
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
        {pasteRequired ? (
          <div className="notice notice--error" role="alert">
            <p>This site does not allow automatic reading. Paste the job posting text above. We keep the link.</p>
          </div>
        ) : (
          create.isError && <ErrorNotice error={create.error} />
        )}
        <div className="row section">
          <button type="submit" className="btn" disabled={create.isPending}>
            Read job posting
          </button>
        </div>
      </form>
    </div>
  );
}
