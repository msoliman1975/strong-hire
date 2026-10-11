/**
 * A voice room without LiveKit, for the browser mocks (VITE_API_MOCKS=all) and the tests. The
 * mocked join returns a "mock:" URL, and the live page uses this connector for it. A scripted
 * interviewer joins, says one line per command, and never ends by itself. It "speaks" each line
 * for a time that fits its length (no audio), then listens, so the avatar moves.
 */
import type { Phase } from "../api/types";
import type { AgentState, VoiceConnector } from "./voice";

/** About 14 characters a second, the pace of the TTS voice. */
export const speakingMs = (line: string) => Math.min(6000, Math.max(800, line.length * 70));

export const MOCK_OPENING = "Hi, thanks for joining. I am your interviewer today. How is your day going?";
export const MOCK_QUESTION = "Tell me about a time you led a project without formal authority.";

const LINES: Record<"hint" | "redo" | "pause" | "resume" | "ready", string> = {
  hint: "A hint: say what you did yourself, and give one number for the result.",
  redo: "Sure. Take a moment, then answer again.",
  pause: "",
  resume: "",
  ready: "Great. Go ahead.",
};

const prepLine = (minutes: number) =>
  `Sure, take ${minutes} ${minutes === 1 ? "minute" : "minutes"} to prepare. The clock is stopped. Tell me when you are ready.`;

export const connectMockVoice: VoiceConnector = async (_join, handlers) => {
  const started = Date.now();
  let paused = false;
  let pausedAt = 0;
  let pausedMs = 0;
  let prepUntil: number | null = null;
  let phase: Phase = "intro";
  let open = true;
  const state = (said: string[]): AgentState => {
    const now = Date.now();
    const elapsedMs = (paused ? pausedAt : now) - started - pausedMs;
    const prepMsLeft = prepUntil === null ? null : Math.max(0, prepUntil - now);
    return { phase, paused, elapsedMs, prepMsLeft, said, receivedAt: now };
  };
  const hold = () => {
    if (paused) return;
    paused = true;
    pausedAt = Date.now();
  };
  const release = () => {
    if (!paused) return;
    paused = false;
    pausedMs += Date.now() - pausedAt;
  };
  let prepTimer: ReturnType<typeof setTimeout> | undefined;
  const endPrep = (line: string) => {
    clearTimeout(prepTimer);
    if (prepUntil === null) return;
    prepUntil = null;
    release();
    say([line]);
  };
  const later = (fn: () => void, ms: number) =>
    setTimeout(() => {
      if (open) fn();
    }, ms);
  let quiet: ReturnType<typeof setTimeout> | undefined;
  const say = (said: string[]) => {
    handlers.onState(state(said));
    const line = said.join(" ");
    if (!line) return;
    clearTimeout(quiet);
    handlers.onActivity("speaking");
    quiet = later(() => handlers.onActivity("listening"), speakingMs(line));
  };

  handlers.onConnection("connected");
  later(() => {
    handlers.onAgentJoined();
    handlers.onInterviewerVoice("female");
    say([MOCK_OPENING]);
  }, 200);
  later(() => {
    phase = "core";
    say([MOCK_QUESTION]);
  }, 800);

  return {
    send: async (command) => {
      if (command === "end") return;
      if (typeof command === "object") {
        if (prepUntil !== null) return;
        prepUntil = Date.now() + command.prep * 60_000;
        hold();
        prepTimer = later(() => endPrep("Time is up. Go ahead whenever you are ready."), command.prep * 60_000);
        later(() => say([prepLine(command.prep)]), 50);
        return;
      }
      if (command === "ready") {
        later(() => endPrep(LINES.ready), 50);
        return;
      }
      if (command === "pause") hold();
      if (command === "resume") release();
      const line = LINES[command];
      later(() => say(line ? [line] : []), 50);
    },
    disconnect: async () => {
      open = false;
      clearTimeout(quiet);
      clearTimeout(prepTimer);
    },
  };
};
