/**
 * CO-2 (UI): a coach session (canvas board A1 Coach session). The conversation is on the left,
 * the story taking shape on the right: the five parts as the coach fills them from the
 * candidate's own words (CO-3), what is still missing and what the coach asks for now (CO-4),
 * and the skills the story could prove. The style switch is CO-5. "Save and exit" saves the
 * title, ends the session and opens the story in the studio.
 *
 * The mic button (CO-6) joins the coach's voice room through useCoachVoice, with a token from
 * POST /coach/sessions/{id}/voice/join (room coach-<id>). When voice is open and the browser has a
 * microphone, the page is voice-first, as on the canvas: a big mic, what the coach is doing now,
 * and "Type instead". `?voice=1` (the mic on Home) starts talking at once.
 */
import "./coach.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useSiteStatus } from "../../api/status";

import { competencyLabel } from "../../labels";
import {
  ErrorNotice,
  Eyebrow,
  Loading,
  Pill,
  STORY_PART_LABEL,
  Segmented,
  StoryPartChip,
} from "../../components/ui";
import { displayStatusOf, STORY_PARTS, storiesApi, storyKeys, type Competency, type Story } from "../stories/api";
import { Strova } from "../../components/strova";
import { StoryStatusBadge } from "../stories/StoriesPage";
import { storiesPath, storyPath } from "../stories/paths";
import {
  ASK_PART,
  coachApi,
  coachKeys,
  useCoachSession,
  type CoachSessionDetail,
  type CoachStyle,
  type CoachTurnResult,
  type StoryPart,
} from "./api";
import { useCoachVoice } from "./useCoachVoice";

/** The title the API gives a new coach story. */
const NEW_STORY_TITLE = "Untitled story";

const STYLE_OPTIONS: { value: CoachStyle; label: string }[] = [
  { value: "gentle", label: "Gentle" },
  { value: "direct", label: "Direct" },
];

const PART_EMPTY: Record<StoryPart, string> = {
  context: "Where you were and what was going on.",
  stakes: "Why it mattered, and what could go wrong.",
  action: "What you did yourself.",
  result: "What changed, with a number if you have one.",
  reflection: "What you learned, or would do differently.",
};

type PartState = "done" | "now" | "next";
const PART_STATE_LABEL: Record<PartState, string> = { done: "Done", now: "Coach is asking", next: "Missing" };

export function CoachSessionPage() {
  const { sessionId = "" } = useParams();
  const detail = useCoachSession(sessionId);
  return (
    <div className="coach stack">
      {detail.isPending && <Loading label="Loading the coach session" />}
      {detail.isError && <ErrorNotice error={detail.error} />}
      {detail.data && <CoachSession key={detail.data.session.id} detail={detail.data} />}
    </div>
  );
}

/** Voice is open on the site (OC-1) and the browser can open a microphone. */
function useVoiceAvailable(): boolean {
  const status = useSiteStatus();
  const mic = typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function";
  return mic && status.data?.voice_sessions_open === true;
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Whole seconds since `on` turned true, ticking each second; null while it is false. */
function useSecondsOn(on: boolean): number | null {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!on) return;
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => {
      window.clearInterval(id);
      setSeconds(0);
    };
  }, [on]);
  return on ? seconds : null;
}

const filled = (story: Story | null, part: StoryPart) => ((story?.[part] ?? "") as string).trim() !== "";

function CoachSession({ detail }: { detail: CoachSessionDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const sessionId = detail.session.id;
  const story = detail.story;
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState(story && story.title !== NEW_STORY_TITLE ? story.title : "");
  const [shows, setShows] = useState<Competency[]>([]); // CoachReply.skills, the latest turn's
  const [voiceLines, setVoiceLines] = useState<string[]>([]); // spoken lines not yet in the turns
  const [spoken, setSpoken] = useState<Set<number>>(() => new Set()); // candidate turns said by voice here
  const voiceAvailable = useVoiceAvailable();
  const [typing, setTyping] = useState(false);
  const [params] = useSearchParams();
  const ended = detail.session.status !== "active";

  const update = (next: Partial<CoachSessionDetail>) =>
    queryClient.setQueryData<CoachSessionDetail>(coachKeys.session(sessionId), (d) => (d ? { ...d, ...next } : d));

  const apply = (result: CoachTurnResult) => {
    const current = queryClient.getQueryData<CoachSessionDetail>(coachKeys.session(sessionId)) ?? detail;
    const nextStory = result.story ?? current.story;
    update({
      turns: [...current.turns, ...result.turns],
      story: nextStory,
      asking_for: result.asking_for,
      missing: STORY_PARTS.filter((p) => !filled(nextStory, p)),
      session: result.ended ? { ...current.session, status: "ended" } : current.session,
    });
    setShows((result.reply.skills ?? []) as Competency[]);
    if (nextStory) void queryClient.invalidateQueries({ queryKey: storyKeys.one(nextStory.id) });
  };

  const turn = useMutation({
    mutationFn: (text: string) => coachApi.turn(sessionId, text),
    onSuccess: (result) => {
      apply(result);
      setDraft("");
    },
  });

  const style = useMutation({
    mutationFn: (next: CoachStyle) => coachApi.style(sessionId, next),
    onMutate: (next) => update({ session: { ...detail.session, style: next } }),
    onError: () => update({ session: detail.session }),
  });

  const done = useMutation({
    mutationFn: async () => {
      const name = title.trim();
      if (story && name && name !== story.title) await storiesApi.update(story.id, { title: name });
      return coachApi.end(sessionId);
    },
    onSuccess: (end) => {
      voice.end().catch(() => undefined);
      void queryClient.invalidateQueries({ queryKey: storyKeys.all });
      queryClient.setQueryData(coachKeys.session(sessionId), end);
      const id = end.session.story_id;
      navigate(id ? storyPath(id) : storiesPath);
    },
  });

  const voice = useCoachVoice(sessionId, {
    onTurn: (said, result) => {
      if (result) {
        const r = result as CoachTurnResult;
        const mine = r.turns.filter((t) => t.speaker === "candidate").map((t) => t.seq);
        if (mine.length) setSpoken((prev) => new Set([...prev, ...mine]));
        apply(r);
      }
      else if (said.length) setVoiceLines((lines) => [...lines, ...said]);
    },
  });
  const voiceLive = voice.status === "live" || voice.status === "connecting" || voice.status === "reconnecting";
  const voiceFirst = voiceAvailable && !typing;
  const listening = useSecondsOn(voice.status === "live" && voice.activity === "listening");

  // `?voice=1`: the candidate pressed a mic to get here, so start talking once.
  const autoStarted = useRef(false);
  const startVoice = voice.start;
  useEffect(() => {
    if (autoStarted.current || ended || params.get("voice") !== "1" || !voiceAvailable) return;
    autoStarted.current = true;
    void startVoice();
  }, [ended, params, startVoice, voiceAvailable]);

  const send = (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (text && !turn.isPending && !ended) turn.mutate(text);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) send(e);
  };

  const heading = story && story.title !== NEW_STORY_TITLE ? story.title : "Build a story";
  // ST-8: the coach's story response has no display status; it is computed the same way.
  const status = story ? displayStatusOf(story) : "draft";
  const ready = status !== "draft";
  const asked = ASK_PART[detail.asking_for];
  const stateOf = (p: StoryPart): PartState => (p === asked && !ended ? "now" : filled(story, p) ? "done" : "next");
  const couldProve = [...new Set([...((story?.skills ?? []) as Competency[]), ...shows])];
  // The canvas tip: while the coach asks what the candidate did, say "I".
  const lastCoach = [...detail.turns].reverse().find((t) => t.speaker === "coach")?.seq;
  const tipOn = !ended && detail.asking_for === "own_role";

  useEffect(() => {
    document.title = `${heading} | Strong Hire`;
  }, [heading]);

  return (
    <>
      <header className="coach__head">
        <Link className="text-link" to={story ? storyPath(story.id) : storiesPath}>
          {story && story.title !== NEW_STORY_TITLE ? "Back to the story" : "Stories"}
        </Link>
        <div className="coach__title">
          <Eyebrow>Craft with Strova</Eyebrow>
          <h1>{heading}</h1>
        </div>
        <div className="coach__style">
          <span className="muted small" aria-hidden="true">
            Coaching style
          </span>
          <Segmented<CoachStyle>
            label="Coaching style"
            options={STYLE_OPTIONS}
            value={detail.session.style}
            onChange={(next) => {
              if (!ended && next !== detail.session.style) style.mutate(next);
            }}
          />
        </div>
        <button className="btn btn--secondary" type="button" onClick={() => done.mutate()} disabled={done.isPending}>
          {done.isPending ? "Saving" : "Save and exit"}
        </button>
      </header>
      {done.isError && <ErrorNotice error={done.error} title="The story was not saved" />}
      {style.isError && <ErrorNotice error={style.error} title="The style did not change" />}

      <div className="coach__body">
        <section className="card coach__chat" aria-label="Conversation">
          {/* The log wraps the list, so the turns keep their list semantics. */}
          <div role="log" aria-live="polite" aria-label="Conversation with your coach">
            <ol className="plain-list coach__turns">
              {detail.turns.map((t) => (
                <li key={t.seq} className="coach-turn" data-speaker={t.speaker} data-testid="coach-turn">
                  {t.speaker === "coach" && (
                    <span className="coach-turn__avatar" aria-hidden="true">
                      <Strova mode="coaching" size={32} />
                    </span>
                  )}
                  <div className="coach-turn__body">
                    <p>
                      <span className="visually-hidden">{t.speaker === "coach" ? "Coach: " : "You: "}</span>
                      {t.text}
                    </p>
                    {t.speaker === "coach" && t.seq === lastCoach && tipOn && (
                      <p className="coach-turn__tip">Tip: say “I”, not “we”</p>
                    )}
                    {t.speaker === "candidate" && spoken.has(t.seq) && <p className="coach-turn__meta">Spoken</p>}
                  </div>
                </li>
              ))}
              {voiceLines.map((line, i) => (
                <li key={`voice-${i}`} className="coach-turn" data-speaker="coach" data-testid="coach-turn">
                  <span className="coach-turn__avatar" aria-hidden="true">
                    <Strova mode="coaching" size={32} />
                  </span>
                  <p>
                    <span className="visually-hidden">Coach: </span>
                    {line}
                  </p>
                </li>
              ))}
            </ol>
          </div>
          <p role="status" className="muted small coach__pending">
            {turn.isPending ? "The coach is thinking" : ""}
          </p>
          {turn.isError && <ErrorNotice error={turn.error} title="Your message was not sent" />}
          {ended ? (
            <p className="notice coach__ended">This session has ended. Your story is saved; press Save and exit to open it.</p>
          ) : voiceFirst ? (
            <div className="coach__voice">
              <button
                type="button"
                className="coach__mic coach__mic--big"
                data-live={voiceLive || undefined}
                aria-label={voiceLive ? "Stop talking to the coach" : "Talk to the coach"}
                disabled={voice.status === "connecting"}
                onClick={() => void (voiceLive ? voice.end() : voice.start())}
              >
                {voiceLive ? <StopIcon /> : <MicIcon />}
              </button>
              <p className="coach__voice-state" role="status">
                {voice.status === "connecting"
                  ? "Connecting"
                  : !voiceLive
                    ? "Tap to talk"
                    : voice.activity === "speaking"
                      ? "Your coach is talking"
                      : voice.activity === "thinking"
                        ? "Your coach is thinking"
                        : `Listening${listening !== null ? ` · ${clock(listening)}` : ""}`}
              </p>
              <button className="btn btn--secondary" type="button" onClick={() => setTyping(true)}>
                Type instead
              </button>
              {voice.error && <p className="field-error">{voice.error}</p>}
            </div>
          ) : (
            <form className="coach__input" onSubmit={send} aria-label="Reply to your coach">
              <button
                type="button"
                className="coach__mic"
                data-live={voiceLive || undefined}
                aria-label={voiceLive ? "Stop talking to the coach" : "Talk to the coach"}
                disabled={voice.status === "connecting"}
                onClick={() => void (voiceLive ? voice.end() : voice.start())}
              >
                <MicIcon />
              </button>
              <label htmlFor="coach-reply" className="visually-hidden">
                Your reply
              </label>
              <textarea
                id="coach-reply"
                rows={2}
                value={draft}
                maxLength={4000}
                placeholder="Type your answer"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKey}
              />
              <button className="btn" type="submit" disabled={!draft.trim() || turn.isPending}>
                Send
              </button>
              {voiceAvailable && (
                <button className="btn btn--quiet coach__talk-instead" type="button" onClick={() => setTyping(false)}>
                  Talk instead
                </button>
              )}
              {voice.error && <p className="field-error">{voice.error}</p>}
            </form>
          )}
        </section>

        <aside className="coach__side stack" aria-label="Story taking shape">
          <section className="card" aria-labelledby="coach-shape-heading">
            {/* ST-12: Strova thinks while the story takes shape, and celebrates when it is Ready. */}
            <div className="coach__strova" data-testid="coach-strova">
              <Strova mode={ready ? "celebrating" : "thinking"} size={72} hat="coach" />
              <span className="muted small">
                {ready ? "Strova saved your story as Ready." : "Strova is shaping your story from your words."}
              </span>
            </div>
            <div className="coach__shape-head">
              <h2 className="coach__shape-title" id="coach-shape-heading">
                Taking shape
              </h2>
              {story && <StoryStatusBadge status={status} />}
            </div>
            {story && (
              <div className="field">
                <label htmlFor="coach-story-title">Story name</label>
                <input
                  id="coach-story-title"
                  type="text"
                  value={title}
                  maxLength={200}
                  placeholder="Name it when you're ready"
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
            )}
            <ol className="plain-list coach__parts" aria-label="Story parts">
              {STORY_PARTS.map((p) => {
                const state = stateOf(p);
                return (
                  <li key={p} className="coach-part" data-part={p} data-state={state} data-testid="coach-part">
                    <p className="coach-part__label">
                      <StoryPartChip part={p} state={state}>
                        {STORY_PART_LABEL[p]} · {PART_STATE_LABEL[state]}
                      </StoryPartChip>
                    </p>
                    <p className={filled(story, p) ? "coach-part__text" : "coach-part__text muted"}>
                      {filled(story, p) ? story?.[p] : PART_EMPTY[p]}
                    </p>
                  </li>
                );
              })}
            </ol>
            {detail.missing.length > 0 && (
              <p className="muted small" data-testid="coach-missing">
                Still missing: {detail.missing.map((p) => STORY_PART_LABEL[p]).join(", ")}
              </p>
            )}
          </section>
          <section className="card" aria-labelledby="coach-prove-heading">
            <h2 id="coach-prove-heading" className="muted small coach__prove-heading">
              This story could prove
            </h2>
            {couldProve.length === 0 ? (
              <p className="muted small">Skills show here as the story takes shape.</p>
            ) : (
              <ul className="plain-list chip-list" aria-label="Skills this story could prove">
                {couldProve.map((s) => (
                  <li key={s}>
                    <Pill state="strong">{competencyLabel(s)}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

function StopIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}
