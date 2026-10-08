/**
 * Live session screen (P10): microphone check, the voice room, phase and timer, captions, Coach
 * controls, reconnect, and the end of the interview. P10 owns apps/web/src/session.
 *
 * Steps: check the microphone -> wait for the interview plan (brief) -> join the room (this starts
 * the session and its clock) -> wait for the interviewer -> live -> end -> debrief page, which
 * waits for the score.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import { keys, useSession } from "../api/hooks";
import { sessionsApi } from "../api/sessions";
import type { Phase, SessionRecord } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { difficultyLabel, interviewTypeLabel, modeLabel, phaseLabel } from "../labels";
import { micProblem, micProblemText, openMicrophone, type MicCheck, type MicProblem } from "./microphone";
import {
  isMockVoice,
  remainingMs,
  type AgentCommand,
  type AgentState,
  type VoiceConnection,
  type VoiceConnector,
} from "./voice";

const PHASES = Object.keys(phaseLabel) as Phase[];
/**
 * How long the page waits for the voice agent to join the room. On a local stack with CPU models,
 * starting the agent's process can take 40 seconds.
 */
export const AGENT_WAIT_MS = 60_000;
/** After this long, the page says that the wait is normal. */
const SLOW_AGENT_MS = 10_000;
/** The voice agent keeps the session this long after a drop (IV-9). */
const RECONNECT_MIN = 2;

// jsdom (Vitest) has no showModal(); the attribute fallback keeps the dialog testable.
const openDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.showModal === "function" ? d.showModal() : d.setAttribute("open", ""));
const closeDialog = (d: HTMLDialogElement | null) =>
  d && (typeof d.close === "function" ? d.close() : d.removeAttribute("open"));

// Both load on demand: LiveKit is large, and the mock is only for the browser mocks and tests.
const connectorFor = async (url: string): Promise<VoiceConnector> =>
  isMockVoice(url) ? (await import("./mockVoice")).connectMockVoice : (await import("./livekitVoice")).connectLiveKit;

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

const clock = (ms: number) => {
  const left = Math.ceil(ms / 1000);
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
};

export function LiveSessionPage() {
  const { sessionId = "" } = useParams();
  const session = useSession(sessionId);

  if (session.isPending) return <Loading label="Loading the session" />;
  if (session.isError) return <ErrorNotice error={session.error} />;
  if (session.data.status !== "created" && session.data.status !== "in_progress")
    return <Navigate to={`/sessions/${sessionId}/debrief`} replace />;
  return <LiveView session={session.data} />;
}

type Stage = "check" | "joining" | "waiting" | "live" | "failed";

function LiveView({ session }: { session: SessionRecord }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const connection = useRef<VoiceConnection | null>(null);
  const [stage, setStage] = useState<Stage>("check");
  const [failure, setFailure] = useState<string | null>(null);
  const [link, setLink] = useState<"connected" | "reconnecting" | "disconnected">("connected");
  const [agent, setAgent] = useState<AgentState | null>(null);
  const [slowAgent, setSlowAgent] = useState(false);
  const now = useNow();
  const { config } = session;
  const sessionId = session.id;

  const toDebrief = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.session(sessionId) });
    void queryClient.invalidateQueries({ queryKey: keys.usage });
    navigate(`/sessions/${sessionId}/debrief`);
  }, [navigate, queryClient, sessionId]);

  const join = useCallback(async () => {
    setStage("joining");
    setFailure(null);
    try {
      await connection.current?.disconnect();
      const ticket = await sessionsApi.joinVoice(sessionId);
      void queryClient.invalidateQueries({ queryKey: keys.session(sessionId) });
      const connect = await connectorFor(ticket.livekit_url);
      setStage("waiting");
      connection.current = await connect(ticket, {
        onAgentJoined: () => setStage("live"),
        onState: (state) => {
          setStage("live");
          setAgent(state);
        },
        onEnded: () => {
          void connection.current?.disconnect();
          toDebrief();
        },
        onConnection: setLink,
      });
    } catch (err) {
      setStage("failed");
      setFailure(
        err instanceof ApiError
          ? err.message
          : "We could not connect to the interview. Check your internet connection, then try again.",
      );
    }
  }, [queryClient, sessionId, toDebrief]);

  // The voice agent should join within seconds. If it does not, say so and offer a retry.
  useEffect(() => {
    if (stage !== "waiting") return;
    const slow = setTimeout(() => setSlowAgent(true), SLOW_AGENT_MS);
    const t = setTimeout(() => {
      setStage("failed");
      setFailure("The interviewer did not join. The voice service may be down. Try again in a minute.");
    }, AGENT_WAIT_MS);
    return () => {
      clearTimeout(slow);
      clearTimeout(t);
      setSlowAgent(false);
    };
  }, [stage]);

  useEffect(() => () => void connection.current?.disconnect(), []);

  const send = (command: AgentCommand) => connection.current?.send(command).catch(() => undefined);

  const end = useMutation({
    mutationFn: async () => {
      await send("end");
      return sessionsApi.end(sessionId);
    },
    onSuccess: (s) => {
      void connection.current?.disconnect();
      queryClient.setQueryData(keys.session(sessionId), s);
      toDebrief();
    },
  });

  const phase: Phase = agent?.phase ?? "intro";
  const paused = agent?.paused ?? false;
  const inRoom = stage === "waiting" || stage === "live";

  return (
    <div className="page--narrow">
      <PageHead title="Interview in progress">
        <p>
          {interviewTypeLabel[config.interview_type]} interview, {difficultyLabel[config.difficulty]} difficulty,{" "}
          {modeLabel[config.mode]} mode
        </p>
      </PageHead>

      {stage === "check" && <MicCheckPanel briefReady={session.brief_ready} onReady={() => void join()} />}
      {stage === "joining" && <Loading label="Connecting to the interview" />}
      {stage === "failed" && (
        <div className="panel" role="alert">
          <p>{failure}</p>
          <div className="row section">
            <button type="button" className="btn" onClick={() => void join()}>
              Try again
            </button>
          </div>
        </div>
      )}

      {inRoom && link === "reconnecting" && (
        <p className="notice" role="status" data-testid="reconnect-banner">
          Connection lost. Reconnecting. Your interview clock is stopped.
        </p>
      )}
      {inRoom && link === "disconnected" && (
        <div className="notice" role="alert" data-testid="reconnect-banner">
          <p>You are disconnected. Rejoin within {RECONNECT_MIN} minutes to go on from the same question.</p>
          <button type="button" className="btn" onClick={() => void join()}>
            Rejoin
          </button>
        </div>
      )}

      {inRoom && (
        <section className="live" aria-label="Interview">
          <div className="row row--between">
            <div>
              <p className="muted">Time left</p>
              <p className="live__timer" aria-live="off" data-testid="timer">
                {clock(remainingMs(config.duration_min, agent, now))}
              </p>
            </div>
            <p className="muted" role="status">
              {stage === "waiting"
                ? slowAgent
                  ? "The interviewer is starting. This can take up to a minute."
                  : "Waiting for the interviewer to join"
                : paused
                  ? "Paused"
                  : "Connected"}
            </p>
          </div>
          <ol className="phases" aria-label="Interview phases">
            {PHASES.map((p) => (
              <li key={p} aria-current={p === phase ? "step" : undefined}>
                {phaseLabel[p]}
              </li>
            ))}
          </ol>
          <div
            className="live__captions"
            aria-live="polite"
            aria-label="What the interviewer said"
            data-testid="captions"
          >
            {agent?.said.length ? (
              agent.said.map((line, i) => <p key={i}>{line}</p>)
            ) : (
              <p className="muted">The interviewer speaks here, and you answer out loud.</p>
            )}
          </div>
          <p className="muted">Your audio is never stored. Only the text of the interview is kept.</p>
          {config.mode === "coach" && (
            <div className="row section">
              <button
                type="button"
                className="btn btn--secondary"
                disabled={stage !== "live"}
                onClick={() => void send(paused ? "resume" : "pause")}
              >
                {paused ? "Resume" : "Pause"}
              </button>
              <button
                type="button"
                className="btn btn--secondary"
                disabled={stage !== "live" || paused}
                onClick={() => void send("hint")}
              >
                Ask for a hint
              </button>
              <button
                type="button"
                className="btn btn--secondary"
                disabled={stage !== "live" || paused}
                onClick={() => void send("redo")}
              >
                Redo my answer
              </button>
            </div>
          )}
        </section>
      )}

      {stage !== "joining" && (
        <div className="row section">
          <button type="button" className="btn btn--danger" onClick={() => openDialog(dialog.current)}>
            End interview
          </button>
        </div>
      )}
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

/** Step 1: the browser asks for the microphone, and the candidate sees that it hears them. */
function MicCheckPanel({ briefReady, onReady }: { briefReady: boolean; onReady: () => void }) {
  const mic = useRef<MicCheck | null>(null);
  const [state, setState] = useState<"idle" | "asking" | "open">("idle");
  const [problem, setProblem] = useState<MicProblem | null>(null);
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState(false);

  useEffect(() => {
    if (state !== "open") return;
    const t = setInterval(() => {
      const value = mic.current?.level() ?? 0;
      setLevel(value);
      if (value > 0.08) setHeard(true);
    }, 100);
    return () => clearInterval(t);
  }, [state]);

  useEffect(() => () => mic.current?.stop(), []);

  const check = async () => {
    setState("asking");
    setProblem(null);
    try {
      mic.current = await openMicrophone();
      setState("open");
    } catch (err) {
      setProblem(micProblem(err));
      setState("idle");
    }
  };

  const start = () => {
    mic.current?.stop();
    mic.current = null;
    onReady();
  };

  return (
    <section className="panel" aria-labelledby="mic-title">
      <h2 id="mic-title">Check your microphone</h2>
      <p>The interview is spoken. Use headphones if you can, so the interviewer does not hear itself.</p>
      {state !== "open" && (
        <button type="button" className="btn" disabled={state === "asking"} onClick={() => void check()}>
          Check my microphone
        </button>
      )}
      {problem && (
        <p className="field-error" role="alert">
          {micProblemText[problem]}
        </p>
      )}
      {state === "open" && (
        <>
          <label htmlFor="mic-level">Say a few words. The bar moves when we hear you.</label>
          <progress id="mic-level" max={1} value={level} />
          <p role="status">{heard ? "We can hear you." : "We cannot hear you yet."}</p>
          {!briefReady && <Loading label="Preparing your interviewer. This takes up to a minute." />}
          <div className="row section">
            <button type="button" className="btn" disabled={!briefReady} onClick={start}>
              Join the interview
            </button>
          </div>
          <p className="muted">The clock starts when you join.</p>
        </>
      )}
    </section>
  );
}
