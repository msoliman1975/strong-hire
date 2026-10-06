import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { keys, useJob } from "../../api/hooks";
import { jobTargetsApi } from "../../api/inputs";
import { gapApi } from "../../api/planned";
import type { JobContext } from "../../api/types";
import { ErrorNotice, Loading, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";

const STAGES = ["Recruiter screen", "Phone screen", "Onsite or final loop", "Not sure"];

type Fields = keyof JobContext | "stage";

/** IN-4: optional context. Saving or skipping starts the gap analysis with the chosen resume. */
export function ContextPage() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const resumeId = params.get("resume");
  const job = useJob(jobId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<Fields, string>>({
    stage: "",
    interviewer_name: "",
    interviewer_role: "",
    recruiter_notes: "",
    concerns: "",
  });

  const finish = useMutation({
    mutationFn: async (input: { stage: string | null; context: JobContext } | null) => {
      if (!resumeId) throw new Error("Choose a resume first.");
      const posting = job.data?.posting;
      if (input && posting) {
        const saved = await jobTargetsApi.update(jobId, { posting, ...input });
        queryClient.setQueryData(keys.job(jobId), saved.job_target);
      }
      return gapApi.start(jobId, { resume_id: resumeId });
    },
    onSuccess: (gap) => {
      queryClient.setQueryData(keys.gap(jobId), gap);
      navigate(`/jobs/${jobId}/gap`);
    },
  });

  const set = (name: Fields) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const value = (s: string) => s.trim() || null;
    finish.mutate({
      stage: value(form.stage),
      context: {
        interviewer_name: value(form.interviewer_name),
        interviewer_role: value(form.interviewer_role),
        recruiter_notes: value(form.recruiter_notes),
        concerns: value(form.concerns),
      },
    });
  };

  if (job.isPending) return <Loading />;

  return (
    <div className="page--narrow">
      <Steps current={2} steps={ONBOARDING_STEPS} />
      <PageHead title="Add context (optional)">
        <p>Anything you know about the interview helps the interviewer focus. You can skip this step.</p>
      </PageHead>
      {job.isError && <ErrorNotice error={job.error} />}
      {!resumeId && (
        <div className="notice notice--error" role="alert">
          <p>
            Choose a resume first. <Link to={`/jobs/${jobId}/resume`}>Go to the resume step</Link>.
          </p>
        </div>
      )}
      <form className="panel" onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="stage">Interview stage</label>
          <select id="stage" value={form.stage} onChange={set("stage")}>
            <option value="">Choose a stage</option>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="interviewer_name">Interviewer name</label>
            <input id="interviewer_name" type="text" value={form.interviewer_name} onChange={set("interviewer_name")} />
          </div>
          <div className="field">
            <label htmlFor="interviewer_role">Interviewer role</label>
            <input id="interviewer_role" type="text" value={form.interviewer_role} onChange={set("interviewer_role")} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="recruiter_notes">Notes from the recruiter</label>
          <textarea id="recruiter_notes" rows={4} value={form.recruiter_notes} onChange={set("recruiter_notes")} />
        </div>
        <div className="field">
          <label htmlFor="concerns">What worries you about this interview?</label>
          <textarea id="concerns" rows={3} value={form.concerns} onChange={set("concerns")} />
        </div>
        {finish.isError && <ErrorNotice error={finish.error} />}
        <div className="row section">
          <button type="submit" className="btn" disabled={finish.isPending || !resumeId}>
            Save and see my gap analysis
          </button>
          <button type="button" className="btn btn--quiet" disabled={finish.isPending || !resumeId} onClick={() => finish.mutate(null)}>
            Skip this step
          </button>
        </div>
      </form>
    </div>
  );
}
