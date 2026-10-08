import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { keys, useResume } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import type { Resume } from "../../api/types";
import { ErrorNotice, Loading, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";

/** One role as the form edits it. Dates are text; an empty end means the current role. */
export interface RoleDraft {
  key: number;
  company: string;
  title: string;
  start: string;
  end: string;
  achievements: string[];
  skills: string[];
}

export interface ResumeDraft {
  roles: RoleDraft[];
  skills: string;
}

/** Field errors by name, for example "role-0-company". Empty when the draft is valid. */
export type DraftErrors = Record<string, string>;

const DATE = /^\d{4}(-(0[1-9]|1[0-2]))?$/;

let nextKey = 1;
const newKey = () => nextKey++;

export function toDraft(resume: Resume): ResumeDraft {
  return {
    roles: resume.roles.map((r) => ({
      key: newKey(),
      company: r.company,
      title: r.title,
      start: r.start ?? "",
      end: r.end ?? "",
      achievements: [...r.achievements],
      skills: [...r.skills],
    })),
    skills: resume.skills.join(", "),
  };
}

/**
 * Checks the draft and builds the Resume to save. Company and title are required, dates are
 * YYYY or YYYY-MM, and empty achievements and skills are dropped. Summary, education and
 * certifications come from the original unchanged.
 */
export function validateResumeDraft(
  draft: ResumeDraft,
  original: Resume,
): { errors: DraftErrors; resume: Resume | null } {
  const errors: DraftErrors = {};
  draft.roles.forEach((role, i) => {
    if (!role.company.trim()) errors[`role-${i}-company`] = "Enter the company.";
    if (!role.title.trim()) errors[`role-${i}-title`] = "Enter the job title.";
    for (const name of ["start", "end"] as const) {
      const value = role[name].trim();
      if (value && !DATE.test(value)) errors[`role-${i}-${name}`] = "Use YYYY or YYYY-MM, for example 2021-03.";
    }
    const start = role.start.trim();
    const end = role.end.trim();
    if (start && end && DATE.test(start) && DATE.test(end) && end < start) {
      errors[`role-${i}-end`] = "The end date is before the start date.";
    }
  });
  if (Object.keys(errors).length > 0) return { errors, resume: null };
  const resume: Resume = {
    ...original,
    roles: draft.roles.map((r) => ({
      company: r.company.trim(),
      title: r.title.trim(),
      start: r.start.trim() || null,
      end: r.end.trim() || null,
      achievements: r.achievements.map((a) => a.trim()).filter(Boolean),
      skills: r.skills,
    })),
    skills: [...new Set(draft.skills.split(",").map((s) => s.trim()).filter(Boolean))],
  };
  return { errors, resume };
}

const contextPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/context?resume=${encodeURIComponent(resumeId)}`;

/** IN-3 "Check your CV": the user fixes the extracted roles and skills, then confirms. */
export function CheckResumePage() {
  const { jobId = "", resumeId = "" } = useParams();
  const record = useResume(resumeId);
  const parsed = record.data?.resume ?? null;

  return (
    <div className="page--narrow">
      <Steps current={1} steps={ONBOARDING_STEPS} />
      <PageHead title="Check your CV">
        <p>
          This is what we read from your CV. Check that each achievement is under the right job, fix
          anything that is wrong, then confirm. We use this version to compare your CV with the job.
        </p>
      </PageHead>
      {record.isError && <ErrorNotice error={record.error} />}
      {(record.isPending || record.data?.status === "pending") && <Loading label="Reading your resume." />}
      {record.data?.deleted && <ErrorNotice error="This CV was deleted. Go back and add a resume." />}
      {parsed && !record.data?.deleted && (
        <ResumeEditor key={resumeId} jobId={jobId} resumeId={resumeId} original={parsed} />
      )}
    </div>
  );
}

function ResumeEditor({ jobId, resumeId, original }: { jobId: string; resumeId: string; original: Resume }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ResumeDraft>(() => toDraft(original));
  const [errors, setErrors] = useState<DraftErrors>({});
  const save = useMutation({
    mutationFn: (resume: Resume) => resumesApi.update(resumeId, resume),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.resume(resumeId), saved);
      void queryClient.invalidateQueries({ queryKey: keys.resumes, exact: true });
      navigate(contextPath(jobId, resumeId));
    },
  });

  const setRole = (index: number, change: Partial<RoleDraft>) =>
    setDraft((d) => ({ ...d, roles: d.roles.map((r, i) => (i === index ? { ...r, ...change } : r)) }));

  const setAchievement = (roleIndex: number, itemIndex: number, text: string) =>
    setRole(roleIndex, {
      achievements: draft.roles[roleIndex].achievements.map((a, j) => (j === itemIndex ? text : a)),
    });

  const removeAchievement = (roleIndex: number, itemIndex: number) =>
    setRole(roleIndex, { achievements: draft.roles[roleIndex].achievements.filter((_, j) => j !== itemIndex) });

  const moveAchievement = (from: number, itemIndex: number, to: number) =>
    setDraft((d) => {
      const item = d.roles[from].achievements[itemIndex];
      return {
        ...d,
        roles: d.roles.map((r, i) => {
          if (i === from) return { ...r, achievements: r.achievements.filter((_, j) => j !== itemIndex) };
          if (i === to) return { ...r, achievements: [...r.achievements, item] };
          return r;
        }),
      };
    });

  const addRole = () =>
    setDraft((d) => ({
      ...d,
      roles: [...d.roles, { key: newKey(), company: "", title: "", start: "", end: "", achievements: [""], skills: [] }],
    }));

  const removeRole = (index: number) => setDraft((d) => ({ ...d, roles: d.roles.filter((_, i) => i !== index) }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const checked = validateResumeDraft(draft, original);
    setErrors(checked.errors);
    if (checked.resume) save.mutate(checked.resume);
  };

  const roleName = (r: RoleDraft, i: number) =>
    r.company.trim() || r.title.trim() ? `${r.title.trim() || "Job"} at ${r.company.trim() || "?"}` : `Job ${i + 1}`;

  const hasErrors = Object.keys(errors).length > 0;

  return (
    <form className="stack" onSubmit={onSubmit} noValidate aria-label="Check your CV">
      {draft.roles.length === 0 && <p className="muted">We found no jobs in your CV. Add one if you want.</p>}
      {draft.roles.map((role, i) => {
        const id = `role-${i}`;
        return (
          <fieldset key={role.key} className="panel" aria-labelledby={`${id}-legend`}>
            <legend id={`${id}-legend`}>{roleName(role, i)}</legend>
            {(
              [
                ["company", "Company"],
                ["title", "Job title"],
                ["start", "Start (YYYY or YYYY-MM)"],
                ["end", "End (YYYY or YYYY-MM, empty if current)"],
              ] as const
            ).map(([name, label]) => {
              const fieldId = `${id}-${name}`;
              const error = errors[fieldId];
              return (
                <div className="field" key={name}>
                  <label htmlFor={fieldId}>{label}</label>
                  <input
                    id={fieldId}
                    value={role[name]}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? `${fieldId}-error` : undefined}
                    onChange={(e) => setRole(i, { [name]: e.target.value })}
                  />
                  {error && (
                    <p className="field-error" id={`${fieldId}-error`}>
                      {error}
                    </p>
                  )}
                </div>
              );
            })}
            <h3>Achievements</h3>
            {role.achievements.length === 0 && <p className="muted">No achievements under this job.</p>}
            <ol className="stack">
              {role.achievements.map((text, j) => {
                const itemId = `${id}-achievement-${j}`;
                return (
                  <li key={j} className="stack">
                    <label htmlFor={itemId} className="hint">
                      Achievement {j + 1} at {roleName(role, i)}
                    </label>
                    <textarea id={itemId} rows={2} value={text} onChange={(e) => setAchievement(i, j, e.target.value)} />
                    <div className="row">
                      {draft.roles.length > 1 && (
                        <>
                          <label htmlFor={`${itemId}-move`} className="muted">
                            Move to
                          </label>
                          <select
                            id={`${itemId}-move`}
                            value=""
                            aria-label={`Move achievement ${j + 1} at ${roleName(role, i)} to another job`}
                            onChange={(e) => {
                              if (e.target.value !== "") moveAchievement(i, j, Number(e.target.value));
                            }}
                          >
                            <option value="">Choose a job</option>
                            {draft.roles.map((other, k) =>
                              k === i ? null : (
                                <option key={other.key} value={k}>
                                  {roleName(other, k)}
                                </option>
                              ),
                            )}
                          </select>
                        </>
                      )}
                      <button
                        type="button"
                        className="btn btn--quiet"
                        aria-label={`Remove achievement ${j + 1} at ${roleName(role, i)}`}
                        onClick={() => removeAchievement(i, j)}
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                );
              })}
            </ol>
            <div className="row">
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => setRole(i, { achievements: [...role.achievements, ""] })}
              >
                Add an achievement
              </button>
              <button
                type="button"
                className="btn btn--quiet"
                aria-label={`Remove the job ${roleName(role, i)}`}
                onClick={() => removeRole(i)}
              >
                Remove this job
              </button>
            </div>
          </fieldset>
        );
      })}
      <div className="row">
        <button type="button" className="btn btn--secondary" onClick={addRole}>
          Add a job
        </button>
      </div>
      <div className="panel field">
        <label htmlFor="resume-skills">Skills</label>
        <p className="hint" id="resume-skills-hint">
          Separate skills with commas.
        </p>
        <textarea
          id="resume-skills"
          rows={3}
          aria-describedby="resume-skills-hint"
          value={draft.skills}
          onChange={(e) => setDraft((d) => ({ ...d, skills: e.target.value }))}
        />
      </div>
      {hasErrors && (
        <p className="field-error" role="alert">
          Fix the fields marked in red, then confirm.
        </p>
      )}
      {save.isError && <ErrorNotice error={save.error} />}
      <div className="row">
        <button type="submit" className="btn" disabled={save.isPending}>
          Confirm and continue
        </button>
      </div>
    </form>
  );
}
