/** PP-2: the days left to the interview, or a prompt to add the date when it is not set. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { CountdownBadge, ErrorNotice } from "../../components/ui";
import { formatDate } from "../../labels";
import { planApi, planKey } from "./api";

export function InterviewDate({
  jobId,
  resumeId,
  date,
  daysLeft,
  editable,
}: {
  jobId: string;
  resumeId: string;
  date: string | null;
  daysLeft: number | null;
  /** A deleted job description cannot be changed (R1). */
  editable: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(date ?? "");
  const save = useMutation({
    mutationFn: (next: string | null) => planApi.setInterviewDate(jobId, next),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: planKey(jobId, resumeId) });
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (value) save.mutate(value);
  };

  if (date && daysLeft !== null && !editing) {
    return (
      <div className="plan-date" data-testid="plan-countdown">
        <CountdownBadge days={daysLeft} />
        <span className="muted">Interview on {formatDate(`${date}T12:00:00`) /* a calendar day: noon keeps it in every time zone */}</span>
        {editable && (
          <button type="button" className="btn btn--quiet" onClick={() => setEditing(true)}>
            Change the date
          </button>
        )}
      </div>
    );
  }
  if (!editable) return null;
  return (
    <form className="plan-date" onSubmit={onSubmit} data-testid="plan-date-form">
      <label htmlFor="plan-interview-date">{date ? "Interview date" : "When is your interview?"}</label>
      <input id="plan-interview-date" type="date" value={value} onChange={(e) => setValue(e.target.value)} />
      <button type="submit" className="btn btn--secondary" disabled={!value || save.isPending}>
        Save the date
      </button>
      {date && (
        <button type="button" className="btn btn--quiet" onClick={() => save.mutate(null)} disabled={save.isPending}>
          Remove the date
        </button>
      )}
      {save.isError && <ErrorNotice error={save.error} title="The date was not saved" />}
    </form>
  );
}
