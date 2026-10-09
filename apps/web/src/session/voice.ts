/**
 * The browser side of the voice room (P10). The voice agent (apps/voice, interview_agent.py)
 * speaks the interview; this module carries its messages to the live page.
 *
 * Agent to browser, data topic "session":
 *   {"type": "state", "phase", "paused", "elapsed_ms", "said": [lines]}  after each interviewer turn
 *   {"type": "ended"}                                                     when the session is over
 * Browser to agent, data topic "coach": {"command": "hint" | "redo" | "pause" | "resume" | "end"}
 */
import type { Phase, VoiceJoin } from "../api/types";

export const SESSION_TOPIC = "session";
export const COACH_TOPIC = "coach";

/** The browser mocks return this URL from the voice join; the live page then uses mockVoice.ts. */
export const MOCK_VOICE_URL = "mock://voice";
export const isMockVoice = (url: string) => url.startsWith("mock:");

export type AgentCommand = "hint" | "redo" | "pause" | "resume" | "end";

export interface AgentState {
  phase: Phase;
  paused: boolean;
  elapsedMs: number;
  said: string[];
  /** Date.now() when the browser got the message; the timer runs on from here. */
  receivedAt: number;
}

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export interface VoiceHandlers {
  onAgentJoined: () => void;
  onState: (state: AgentState) => void;
  onEnded: () => void;
  onConnection: (state: ConnectionState) => void;
}

export interface VoiceConnection {
  send: (command: AgentCommand) => Promise<void>;
  disconnect: () => Promise<void>;
}

export type VoiceConnector = (join: VoiceJoin, handlers: VoiceHandlers) => Promise<VoiceConnection>;

export type AgentMessage = { type: "state"; state: AgentState } | { type: "ended" };

/** Reads one agent message. Unknown or broken messages return null. */
export function parseAgentMessage(data: Uint8Array, now = Date.now()): AgentMessage | null {
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder().decode(data));
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null) return null;
  const m = raw as Record<string, unknown>;
  if (m.type === "ended") return { type: "ended" };
  if (m.type !== "state" || typeof m.phase !== "string") return null;
  return {
    type: "state",
    state: {
      phase: m.phase as Phase,
      paused: m.paused === true,
      elapsedMs: typeof m.elapsed_ms === "number" ? m.elapsed_ms : 0,
      said: Array.isArray(m.said) ? m.said.filter((s): s is string => typeof s === "string") : [],
      receivedAt: now,
    },
  };
}

export const encodeCommand = (command: AgentCommand) => new TextEncoder().encode(JSON.stringify({ command }));

/** Milliseconds left on the interview clock. The clock stops while paused. */
export function remainingMs(durationMin: number, state: AgentState | null, now: number): number {
  if (!state) return durationMin * 60_000;
  const elapsed = state.elapsedMs + (state.paused ? 0 : Math.max(0, now - state.receivedAt));
  return Math.max(0, durationMin * 60_000 - elapsed);
}
