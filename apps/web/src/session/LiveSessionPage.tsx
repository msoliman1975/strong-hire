/**
 * Live session screen. Placeholder: P10 connects it to the voice agent (LiveKit), adds the mic
 * check, the latency test, phase updates and reconnect handling. P10 owns apps/web/src/session.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import { keys, useSession } from "../api/hooks";
import { sessionsApi } from "../api/planned";
import type { Phase } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { difficultyLabel, interviewTypeLabel, modeLabel, phaseLabel } from "../labels";

const PHASES = Object.keys(phaseLabel) as Phase[];

// jsdom (Vitest) has no showModal(); the attribute fallback keeps the dialog testable.
const openDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.showModal === "function" ? d.showModal() : d.setAttribute("open", ""));
const closeDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.close === "function" ? d.close() : d.removeAttribute("open"));

function useRemaining(startedAt: string | null, durationMin: number): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const start = startedAt ? Date.parse(startedAt) : now;
  const left = Math.max(0, durationMin * 60 - Math.floor((now - start) / 1000));
  const m = Math.floor(left / 60);
  const s = left % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function LiveSessionPage() {
  const { sessionId = "" } = useParams();
  const session = useSession(sessionId);

  if (session.isPending) return <Loading label="Loading the session" />;
  if (session.isError) return <ErrorNotice error={session.error} />;
  if (session.data.status !== "in_progress") return <Navigate to={`/sessions/${sessionId}/debrief`} replace />;
  return <LiveView sessionId={sessionId} />;
}

function LiveView({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const data = session.data!;
  const remaining = useRemaining(data.started_at, data.config.duration_min);
  const phase: Phase = "intro";

  const end = useMutation({
    mutationFn: () => sessionsApi.end(sessionId),
    onSuccess: (s) => {
      queryClient.setQueryData(keys.session(sessionId), s);
      void queryClient.invalidateQueries({ queryKey: keys.usage });
      navigate(`/sessions/${sessionId}/debrief`);
    },
  });

  const { config } = data;
  return (
    <div className="page--narrow">
      <PageHead title="Interview in progress">
        <p>
          {interviewTypeLabel[config.interview_type]} interview, {difficultyLabel[config.difficulty]} difficulty,{" "}
          {modeLabel[config.mode]} mode
        </p>
      </PageHead>
      <section className="live" aria-label="Interview">
        <div className="row row--between">
          <div>
            <p className="muted">Time left</p>
            <p className="live__timer" aria-live="off" data-testid="timer">
              {remaining}
            </p>
          </div>
          <p className="muted">Voice is not connected in this build.</p>
        </div>
        <ol className="phases" aria-label="Interview phases">
          {PHASES.map((p) => (
            <li key={p} aria-current={p === phase ? "step" : undefined}>
              {phaseLabel[p]}
            </li>
          ))}
        </ol>
        <p>The interviewer speaks here, and you answer out loud. Your audio is never stored.</p>
        <div className="row section">
          {config.mode === "coach" && (
            <>
              <button type="button" className="btn btn--secondary" disabled>
                Pause
              </button>
              <button type="button" className="btn btn--secondary" disabled>
                Ask for a hint
              </button>
              <button type="button" className="btn btn--secondary" disabled>
                Redo my answer
              </button>
            </>
          )}
          <button type="button" className="btn btn--danger" onClick={() => openDialog(dialog.current)}>
            End interview
          </button>
        </div>
      </section>
      {end.isError && <ErrorNotice error={end.error} />}

      <dialog ref={dialog} aria-labelledby="end-title" aria-describedby="end-text">
        <h2 id="end-title">End the interview?</h2>
        <p id="end-text">Your debrief is ready about a minute after you end the interview.</p>
        <div className="row row--end">
          <button type="button" className="btn btn--quiet" onClick={() => closeDialog(dialog.current)}>
            Keep going
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={end.isPending}
            onClick={() => {
              closeDialog(dialog.current);
              end.mutate();
            }}
          >
            End interview
          </button>
        </div>
      </dialog>
    </div>
  );
}
