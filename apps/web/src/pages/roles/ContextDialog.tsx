/** IN-4 in a dialog (mockup #role, "Know anything about this interview?"): the stage, the
 * interviewer, recruiter notes and worries. Saved on the job; the next take's brief uses them. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { keys } from "../../api/hooks";
import { jobTargetsApi } from "../../api/inputs";
import type { JobTargetOut } from "../../api/types";
import { ErrorNotice } from "../../components/ui";

type Field = "stage" | "interviewer_name" | "interviewer_role" | "recruiter_notes" | "concerns";

export function ContextDialog({ job }: { job: JobTargetOut }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<Field, string>>({
    stage: job.stage ?? "",
    interviewer_name: job.context.interviewer_name ?? "",
    interviewer_role: job.context.interviewer_role ?? "",
    recruiter_notes: job.context.recruiter_notes ?? "",
    concerns: job.context.concerns ?? "",
  });
  const save = useMutation({
    mutationFn: async () => {
      if (!job.posting) throw new Error("The job posting is still being read.");
      const value = (s: string) => s.trim() || null;
      return jobTargetsApi.update(job.id, {
        posting: job.posting,
        stage: value(form.stage),
        context: {
          interviewer_name: value(form.interviewer_name),
          interviewer_role: value(form.interviewer_role),
          recruiter_notes: value(form.recruiter_notes),
          concerns: value(form.concerns),
        },
      });
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(job.id), saved.job_target);
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      dialog.current?.close();
    },
  });
  const set = (name: Field) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [name]: e.target.value }));
  const has = Object.values(form).some((v) => v.trim());
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <>
      <button type="button" className="sx-btn ghost sm" onClick={() => dialog.current?.showModal()}>
        {has ? "Edit what you know" : "Add what you know"}
      </button>
      <dialog ref={dialog} aria-labelledby="ctx-heading" className="sx-dialog">
        <form className="sx-card" onSubmit={onSubmit}>
          <h2 id="ctx-heading">What you know about this interview</h2>
          <div className="sx-field">
            <label htmlFor="ctx-stage">Interview stage</label>
            <input id="ctx-stage" value={form.stage} onChange={set("stage")} placeholder="For example: Onsite" />
          </div>
          <div className="sx-grid2">
            <div className="sx-field">
              <label htmlFor="ctx-name">Interviewer name</label>
              <input id="ctx-name" value={form.interviewer_name} onChange={set("interviewer_name")} />
            </div>
            <div className="sx-field">
              <label htmlFor="ctx-role">Interviewer role</label>
              <input id="ctx-role" value={form.interviewer_role} onChange={set("interviewer_role")} />
            </div>
          </div>
          <div className="sx-field">
            <label htmlFor="ctx-notes">Notes from the recruiter</label>
            <textarea id="ctx-notes" rows={3} value={form.recruiter_notes} onChange={set("recruiter_notes")} />
          </div>
          <div className="sx-field">
            <label htmlFor="ctx-worries">What worries you about this interview?</label>
            <textarea id="ctx-worries" rows={2} value={form.concerns} onChange={set("concerns")} />
          </div>
          {save.isError && <ErrorNotice error={save.error} />}
          <div className="sx-row">
            <button type="submit" className="sx-btn" disabled={save.isPending}>
              Save
            </button>
            <button type="button" className="sx-btn quiet" onClick={() => dialog.current?.close()}>
              Cancel
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
