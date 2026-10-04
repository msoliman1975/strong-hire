import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { keys, useJob } from "../../api/hooks";
import { gapApi, jobsApi, type JobContext } from "../../api/planned";
import { ErrorNotice, Loading, ONBOARDING_STEPS, PageHead, Steps } from "../../components/ui";

const STAGES = ["Recruiter screen", "Phone screen", "Onsite or final loop", "Not sure"];

/** IN-4: optional context. Saving or skipping starts the gap analysis. */
export function ContextPage() {
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<keyof JobContext, string>>({
    stage: "",
    interviewer: "",
    recruiter_notes: "",
    concerns: "",
  });

  const finish = useMutation({
    mutationFn: async (context: JobContext | null) => {
      if (context) await jobsApi.setContext(jobId, context);
      return gapApi.start(jobId);
    },
    onSuccess: (gap) => {
      queryClient.setQueryData(keys.gap(jobId), gap);
      navigate(`/jobs/${jobId}/gap`);
    },
  });

  const set = (name: keyof JobContext) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const value = (s: string) => s.trim() || null;
    finish.mutate({
      stage: value(form.stage),
      interviewer: value(form.interviewer),
      recruiter_notes: value(form.recruiter_notes),
      concerns: value(form.concerns),
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
        <div className="field">
          <label htmlFor="interviewer">Interviewer name or role</label>
          <input id="interviewer" type="text" value={form.interviewer} onChange={set("interviewer")} />
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
          <button type="submit" className="btn" disabled={finish.isPending}>
            Save and see my gap analysis
          </button>
          <button type="button" className="btn btn--quiet" disabled={finish.isPending} onClick={() => finish.mutate(null)}>
            Skip this step
          </button>
        </div>
      </form>
    </div>
  );
}
