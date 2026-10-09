/**
 * A voice room without LiveKit, for the browser mocks (VITE_API_MOCKS=all) and the tests. The
 * mocked join returns a "mock:" URL, and the live page uses this connector for it. A scripted
 * interviewer joins, says one line per command, and never ends by itself.
 */
import type { Phase } from "../api/types";
import type { AgentCommand, AgentState, VoiceConnector } from "./voice";

export const MOCK_OPENING = "Hi, thanks for joining. I am your interviewer today. How is your day going?";
export const MOCK_QUESTION = "Tell me about a time you led a project without formal authority.";

const LINES: Record<Exclude<AgentCommand, "end">, string> = {
  hint: "A hint: say what you did yourself, and give one number for the result.",
  redo: "Sure. Take a moment, then answer again.",
  pause: "",
  resume: "",
};

export const connectMockVoice: VoiceConnector = async (_join, handlers) => {
  const started = Date.now();
  let paused = false;
  let pausedAt = 0;
  let pausedMs = 0;
  let phase: Phase = "intro";
  let open = true;
  const state = (said: string[]): AgentState => {
    const now = Date.now();
    const elapsedMs = (paused ? pausedAt : now) - started - pausedMs;
    return { phase, paused, elapsedMs, said, receivedAt: now };
  };
  const later = (fn: () => void, ms: number) =>
    setTimeout(() => {
      if (open) fn();
    }, ms);

  handlers.onConnection("connected");
  later(() => {
    handlers.onAgentJoined();
    handlers.onState(state([MOCK_OPENING]));
  }, 200);
  later(() => {
    phase = "core";
    handlers.onState(state([MOCK_QUESTION]));
  }, 800);

  return {
    send: async (command) => {
      if (command === "end") return;
      if (command === "pause" && !paused) {
        paused = true;
        pausedAt = Date.now();
      }
      if (command === "resume" && paused) {
        paused = false;
        pausedMs += Date.now() - pausedAt;
      }
      const line = LINES[command];
      later(() => handlers.onState(state(line ? [line] : [])), 50);
    },
    disconnect: async () => {
      open = false;
    },
  };
};
