import { useEffect, useRef, useState } from "react";

import { useJobs } from "../api/hooks";
import type { Difficulty, InterviewType, Level, Mode, SessionConfig, Turn } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { difficultyLabel, interviewTypeLabel, levelLabel, modeLabel, phaseLabel } from "../labels";
import type { CoachCommand, Debrief, SessionRecord } from "./textInterviewApi";
import { textInterviewApi as api } from "./textInterviewApi";

type Stage = "setup" | "preparing" | "open" | "ended";

const POLL_MS = 2000;
const BRIEF_TIMEOUT_MS = 3 * 60 * 1000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Dev builds only: run a real interview by typing. Uses the text channel of the sessions API
 * (P7, PL-7) with the active model profile, so it shows the real interviewer and the real
 * debrief. The voice interview comes with P7 part 3 and P10.
 */
export function DevTextInterviewPage() {
  const jobs = useJobs();
  const [pickedJob, setJobId] = useState("");
  const [type, setType] = useState<InterviewType>("behavioral");
  const [difficulty, setDifficulty] = useState<Difficulty>("realistic");
  const [mode, setMode] = useState<Mode>("realistic");
  // 10 by default: a free account may start mini interviews only.
  const [duration, setDuration] = useState<SessionConfig["duration_min"]>(10);
  const [pickedLevel, setLevel] = useState<Level | null>(null);

  const [stage, setStage] = useState<Stage>("setup");
  const [session, setSession] = useState<SessionRecord | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [phase, setPhase] = useState("intro");
  const [paused, setPaused] = useState(false);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [debrief, setDebrief] = useState<Debrief | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const ready = (jobs.data ?? []).filter((j) => j.job_target.status === "extracted");
  // Defaults until the user picks: the newest ready job, and its level.
  const jobId = pickedJob || ready[0]?.job_target.id || "";
  const job = ready.find((j) => j.job_target.id === jobId);
  const level: Level = pickedLevel ?? (job?.job_target.level as Level | null) ?? "mid";

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [turns]);

  async function run<T>(step: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await step();
    } catch (err) {
      setError(err);
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function waitForDebrief(id: string) {
    for (let i = 0; i < 90; i++) {
      const d = await api.debrief(id);
      setDebrief(d);
      if (d.status !== "scoring") return;
      await sleep(POLL_MS);
    }
  }

  async function finish(id: string) {
    setStage("ended");
    await waitForDebrief(id);
  }

  async function start() {
    await run(async () => {
      const created = await api.create(jobId, {
        interview_type: type,
        difficulty,
        mode,
        duration_min: duration,
        level,
      });
      setSession(created);
      setStage("preparing");
      const deadline = Date.now() + BRIEF_TIMEOUT_MS;
      let current = created;
      while (!current.brief_ready) {
        if (Date.now() > deadline) throw new Error("The interview plan was not ready in 3 minutes.");
        await sleep(POLL_MS);
        current = await api.get(created.id);
      }
      const opened = await api.open(created.id);
      setTurns(opened.turns as Turn[]);
      setPhase(opened.phase);
      setStage("open");
    });
  }

  async function send() {
    const text = answer.trim();
    if (!session || !text) return;
    const mine: Turn = {
      speaker: "candidate",
      phase: phase as Turn["phase"],
      text,
      start_ms: 0,
      end_ms: 0,
      question_ref: null,
    };
    setTurns((t) => [...t, mine]);
    setAnswer("");
    const out = await run(() => api.turn(session.id, text));
    if (!out) return;
    setTurns((t) => [...t, ...(out.turns as Turn[])]);
    setPhase(out.phase);
    if (out.ended) await finish(session.id);
  }

  async function coach(command: CoachCommand) {
    if (!session) return;
    const out = await run(() => api.coach(session.id, command));
    if (!out) return;
    if (command === "pause") setPaused(true);
    if (command === "resume") setPaused(false);
    setTurns((t) => [...t, ...(out.turns as Turn[])]);
  }

  async function endNow() {
    if (!session) return;
    const out = await run(() => api.end(session.id));
    if (out) await finish(session.id);
  }

  return (
    <div className="dev-interview">
      <PageHead title="Text interview (dev only)">
        Type your answers. The interviewer, the timer and the debrief are real and use the active
        model profile. Voice comes later.
      </PageHead>
      {error !== null && <ErrorNotice error={error} title="The request failed." />}

      {stage === "setup" && (
        <form
          className="dev-interview__setup"
          onSubmit={(e) => {
            e.preventDefault();
            void start();
          }}
        >
          {jobs.isPending && <Loading label="Loading your jobs" />}
          {jobs.data && ready.length === 0 && <p>Add a job with a resume and a gap analysis first.</p>}
          <label>
            Job
            <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
              {ready.map((j) => (
                <option key={j.job_target.id} value={j.job_target.id}>
                  {j.job_target.posting?.title ?? "Job"} at {j.job_target.posting?.company_name ?? "?"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Interview type
            <select value={type} onChange={(e) => setType(e.target.value as InterviewType)}>
              {(Object.keys(interviewTypeLabel) as InterviewType[]).map((t) => (
                <option key={t} value={t}>
                  {interviewTypeLabel[t]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Difficulty
            <select value={difficulty} onChange={(e) => setDifficulty(e.target.value as Difficulty)}>
              {(Object.keys(difficultyLabel) as Difficulty[]).map((d) => (
                <option key={d} value={d}>
                  {difficultyLabel[d]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Mode
            <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              {(Object.keys(modeLabel) as Mode[]).map((m) => (
                <option key={m} value={m}>
                  {modeLabel[m]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Duration
            <select
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value) as SessionConfig["duration_min"])}
            >
              <option value={10}>10 minutes (mini)</option>
              <option value={30}>30 minutes</option>
              <option value={45}>45 minutes</option>
            </select>
          </label>
          <label>
            Level
            <select value={level} onChange={(e) => setLevel(e.target.value as Level)}>
              {(Object.keys(levelLabel) as Level[]).map((l) => (
                <option key={l} value={l}>
                  {levelLabel[l]}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn" disabled={busy || !jobId}>
            Start text interview
          </button>
        </form>
      )}

      {stage === "preparing" && <Loading label="Building the interview plan (about 10 to 30 seconds)" />}

      {(stage === "open" || stage === "ended") && (
        <section className="dev-interview__chat" aria-label="Transcript">
          <ol className="dev-interview__turns">
            {turns.map((t, i) => (
              <li key={i} className={`dev-turn dev-turn--${t.speaker}`}>
                <span className="dev-turn__who">
                  {t.speaker === "interviewer" ? "Interviewer" : "You"}
                  <span className="muted"> · {phaseLabel[t.phase] ?? t.phase}</span>
                </span>
                <span>{t.text}</span>
              </li>
            ))}
          </ol>
          <div ref={endRef} />
          {stage === "open" && (
            <form
              className="dev-interview__answer"
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
            >
              <label htmlFor="dev-answer">Your answer</label>
              <textarea
                id="dev-answer"
                rows={4}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    void send();
                  }
                }}
                disabled={busy || paused}
              />
              <div className="dev-interview__buttons">
                <button type="submit" className="btn" disabled={busy || paused || !answer.trim()}>
                  {busy ? "Waiting for the interviewer" : "Send (Ctrl+Enter)"}
                </button>
                {mode === "coach" && (
                  <>
                    <button type="button" className="btn btn--quiet" disabled={busy || paused} onClick={() => void coach("hint")}>
                      Hint
                    </button>
                    <button type="button" className="btn btn--quiet" disabled={busy || paused} onClick={() => void coach("redo")}>
                      Redo answer
                    </button>
                    <button
                      type="button"
                      className="btn btn--quiet"
                      disabled={busy}
                      onClick={() => void coach(paused ? "resume" : "pause")}
                    >
                      {paused ? "Resume" : "Pause"}
                    </button>
                  </>
                )}
                <button type="button" className="btn btn--quiet" disabled={busy} onClick={() => void endNow()}>
                  End interview
                </button>
              </div>
            </form>
          )}
        </section>
      )}

      {stage === "ended" && (
        <section className="dev-interview__debrief" aria-label="Debrief">
          <h2>Debrief</h2>
          {(!debrief || debrief.status === "scoring") && <Loading label="Scoring the interview" />}
          {debrief?.status === "failed" && <p>Scoring failed. See the worker log.</p>}
          {debrief?.status === "ready" && debrief.scorecard && (
            <>
              <p>
                <strong>{debrief.scorecard.hire_signal}</strong>
              </p>
              <p>{debrief.scorecard.rationale}</p>
              <ul>
                {debrief.scorecard.competency_scores.map((c) => (
                  <li key={c.competency}>
                    {c.competency.replace(/_/g, " ")}: {c.score} of 4
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </div>
  );
}
