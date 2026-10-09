import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { keys, useJob, useJobTask } from "../../api/hooks";
import { jobProblem, jobTargetsApi } from "../../api/inputs";
import type { JobPosting, JobTargetOut, Level, RoleFamily } from "../../api/types";
import { ErrorNotice, Loading, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";
import { levelLabel, roleFamilyLabel } from "../../labels";
import type { NewJobReturn } from "../../paths";
import { afterConfirmPath, confirmPath, MIN_POSTING_CHARS, newJobReturn } from "./NewJobPage";

const lines = (value: string) =>
  value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

export function ConfirmJobPage() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const then = newJobReturn(params.get("then"));
  const task = useJobTask(jobId, params.get("task"));
  const problem = jobProblem(task.data);
  const job = useJob(jobId, problem === null);

  return (
    <div className="page--narrow">
      {then === "rehearsal" && <Steps current={0} steps={ONBOARDING_STEPS} />}
      {job.isPending && <Loading label="Loading the job" />}
      {job.isError && <ErrorNotice error={job.error} />}
      {task.isError && <ErrorNotice error={task.error} />}
      {job.data && problem && <PasteInstead job={job.data} message={problem.message} then={then} />}
      {job.data?.status === "pending" && !problem && (
        <>
          <PageHead title="Reading the job posting" />
          <Loading label="Reading the posting. This takes up to a minute." />
        </>
      )}
      {job.data?.status === "extracted" && job.data.posting && (
        <PostingForm key={job.data.id} job={job.data} posting={job.data.posting} then={then} />
      )}
    </div>
  );
}

/** IN-1: a link that cannot be read falls back to pasting the text. The link is kept. */
function PasteInstead({ job, message, then }: { job: JobTargetOut; message: string; then: NewJobReturn }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => jobTargetsApi.create({ url: job.source_url, text: text.trim() }),
    onSuccess: (accepted) =>
      navigate(confirmPath(accepted.job_target.id, accepted.job?.id, then), { replace: true }),
  });
  return (
    <>
      <PageHead title="Paste the job posting" />
      <div className="notice notice--error" role="alert">
        <p>{message}</p>
      </div>
      <form
        className="panel"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim().length < MIN_POSTING_CHARS) {
            setError(`Paste the full posting (at least ${MIN_POSTING_CHARS} characters).`);
            return;
          }
          setError(null);
          create.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="paste-text">Job posting text</label>
          <textarea id="paste-text" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
          {error && <p className="field-error">{error}</p>}
        </div>
        {create.isError && <ErrorNotice error={create.error} />}
        <button type="submit" className="btn" disabled={create.isPending}>
          Read job posting
        </button>
      </form>
    </>
  );
}

/** IN-2: the user confirms or edits what was extracted. */
function PostingForm({ job, posting, then }: { job: JobTargetOut; posting: JobPosting; then: NewJobReturn }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    company_name: posting.company_name,
    title: posting.title,
    role_family: posting.role_family,
    level: posting.level ?? "",
    level_label: posting.level_label ?? "",
    team: posting.team ?? "",
    location: posting.location ?? "",
    must_have_skills: posting.must_have_skills.join("\n"),
    nice_to_have_skills: posting.nice_to_have_skills.join("\n"),
    responsibilities: posting.responsibilities.join("\n"),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    // The stage and context are saved on the same call; keep what the job target has.
    mutationFn: (p: JobPosting) => jobTargetsApi.update(job.id, { posting: p, stage: job.stage, context: job.context }),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(job.id), saved.job_target);
      navigate(afterConfirmPath(job.id, then));
    },
  });

  const set = (name: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!form.company_name.trim()) next.company_name = "Enter the company name.";
    if (!form.title.trim()) next.title = "Enter the job title.";
    setErrors(next);
    if (Object.keys(next).length) return;
    save.mutate({
      company_name: form.company_name.trim(),
      title: form.title.trim(),
      role_family: form.role_family,
      level: form.level ? (form.level as Level) : null,
      level_label: form.level_label.trim() || null,
      team: form.team.trim() || null,
      location: form.location.trim() || null,
      must_have_skills: lines(form.must_have_skills),
      nice_to_have_skills: lines(form.nice_to_have_skills),
      responsibilities: lines(form.responsibilities),
      source_url: posting.source_url,
    });
  };

  const textField = (name: "company_name" | "title" | "level_label" | "team" | "location", label: string) => (
    <div className="field">
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        type="text"
        value={form[name]}
        onChange={set(name)}
        aria-invalid={errors[name] ? true : undefined}
        aria-describedby={errors[name] ? `${name}-error` : undefined}
      />
      {errors[name] && (
        <p id={`${name}-error`} className="field-error">
          {errors[name]}
        </p>
      )}
    </div>
  );

  const listField = (name: "must_have_skills" | "nice_to_have_skills" | "responsibilities", label: string) => (
    <div className="field">
      <label htmlFor={name}>{label}</label>
      <p className="hint" id={`${name}-hint`}>
        One per line.
      </p>
      <textarea id={name} rows={4} value={form[name]} onChange={set(name)} aria-describedby={`${name}-hint`} />
    </div>
  );

  return (
    <>
      <PageHead title="Check the job details">
        <p>We read these from the posting. Fix anything that is wrong. The interview is built from them.</p>
      </PageHead>
      {job.generic_mode === false && (
        <div className="notice" role="status">
          <p>
            We have an interview profile for <strong>{posting.company_name}</strong>. Your interviewer follows its
            interview style.
          </p>
        </div>
      )}
      {job.generic_mode === true && (
        <div className="notice" role="status">
          <p>We do not have an interview profile for this company. Your interview uses a general style.</p>
        </div>
      )}
      <form className="panel" onSubmit={onSubmit} noValidate>
        <div className="grid-2">
          {textField("company_name", "Company")}
          {textField("title", "Job title")}
          <div className="field">
            <label htmlFor="role_family">Role family</label>
            <select id="role_family" value={form.role_family} onChange={set("role_family")}>
              {(Object.keys(roleFamilyLabel) as RoleFamily[]).map((r) => (
                <option key={r} value={r}>
                  {roleFamilyLabel[r]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="level">Level</label>
            <select id="level" value={form.level} onChange={set("level")}>
              <option value="">Not sure</option>
              {(Object.keys(levelLabel) as Level[]).map((l) => (
                <option key={l} value={l}>
                  {levelLabel[l]}
                </option>
              ))}
            </select>
          </div>
          {textField("level_label", "Level as written in the posting")}
          {textField("team", "Team")}
          {textField("location", "Location")}
        </div>
        {listField("must_have_skills", "Must-have skills")}
        {listField("nice_to_have_skills", "Nice-to-have skills")}
        {listField("responsibilities", "Responsibilities")}
        {save.isError && <ErrorNotice error={save.error} />}
        <div className="row section">
          <button type="submit" className="btn" disabled={save.isPending}>
            Save and continue
          </button>
        </div>
      </form>
    </>
  );
}
