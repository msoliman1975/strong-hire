/**
 * The browser side of the voice room (P10). The voice agent (apps/voice, interview_agent.py)
 * speaks the interview; this module carries its messages to the live page.
 *
 * Agent to browser, data topic "session":
 *   {"type": "state", "phase", "paused", "elapsed_ms", "prep_ms_left", "said": [lines]}
 *                                                                         after each interviewer turn
 *   {"type": "ended"}                                                     when the session is over
 * Browser to agent, data topic "coach": {"command": "hint" | "redo" | "pause" | "resume" | "end"}.
 * In every mode (IV-11): {"command": "prep", "minutes": 1 | 3} starts prep time, and
 * {"command": "ready"} ends it.
 *
 * LiveKit Agents also sets the participant attribute "lk.agent.state" (listening, thinking,
 * speaking). The interviewer avatar shows it, and moves its mouth from the agent's audio track.
 * The voice agent sets "sh.interviewer.voice" (female or male), and the avatar shows a face that
 * matches the voice.
 */
import type { Phase, VoiceJoin } from "../api/types";

export const SESSION_TOPIC = "session";
export const COACH_TOPIC = "coach";

/** The browser mocks return this URL from the voice join; the live page then uses mockVoice.ts. */
export const MOCK_VOICE_URL = "mock://voice";
export const isMockVoice = (url: string) => url.startsWith("mock:");

/** Prep time the candidate can ask for with a button (IV-11). */
export type PrepMinutes = 1 | 3;
export const PREP_MINUTES: PrepMinutes[] = [1, 3];

export type AgentCommand = "hint" | "redo" | "pause" | "resume" | "end" | "ready" | { prep: PrepMinutes };

export interface AgentState {
  phase: Phase;
  paused: boolean;
  elapsedMs: number;
  /** Prep time left when the message was sent (IV-11), or null when the candidate is not preparing. */
  prepMsLeft: number | null;
  /** In the core phase: the question being asked and how many are planned ("2 of 3"). */
  question?: number | null;
  questions?: number | null;
  said: string[];
  /** Date.now() when the browser got the message; the timer runs on from here. */
  receivedAt: number;
}

/** What the interviewer is doing now. "idle": not in the room yet, or a state we do not know. */
export type AgentActivity = "idle" | "listening" | "thinking" | "speaking";

export const AGENT_STATE_ATTRIBUTE = "lk.agent.state";

export function parseAgentActivity(value: string | undefined): AgentActivity {
  return value === "listening" || value === "thinking" || value === "speaking" ? value : "idle";
}

/** How the interviewer's TTS voice sounds (IV-10). */
export type InterviewerVoice = "female" | "male";

export const INTERVIEWER_VOICE_ATTRIBUTE = "sh.interviewer.voice";

export function parseInterviewerVoice(value: string | undefined): InterviewerVoice | null {
  return value === "female" || value === "male" ? value : null;
}

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export interface VoiceHandlers {
  onAgentJoined: () => void;
  onState: (state: AgentState) => void;
  onEnded: () => void;
  onConnection: (state: ConnectionState) => void;
  onActivity: (activity: AgentActivity) => void;
  /** The interviewer's audio, for the avatar's lip sync. null when it stops. */
  onAgentAudio: (track: MediaStreamTrack | null) => void;
  onInterviewerVoice: (voice: InterviewerVoice) => void;
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
      prepMsLeft: typeof m.prep_ms_left === "number" ? m.prep_ms_left : null,
      question: typeof m.question === "number" ? m.question : null,
      questions: typeof m.questions === "number" ? m.questions : null,
      said: Array.isArray(m.said) ? m.said.filter((s): s is string => typeof s === "string") : [],
      receivedAt: now,
    },
  };
}

export const encodeCommand = (command: AgentCommand) =>
  new TextEncoder().encode(
    JSON.stringify(typeof command === "string" ? { command } : { command: "prep", minutes: command.prep }),
  );

/** Milliseconds left on the interview clock. The clock stops while paused. */
export function remainingMs(durationMin: number, state: AgentState | null, now: number): number {
  if (!state) return durationMin * 60_000;
  const elapsed = state.elapsedMs + (state.paused ? 0 : Math.max(0, now - state.receivedAt));
  return Math.max(0, durationMin * 60_000 - elapsed);
}

/** Milliseconds of prep time left (IV-11), or null when the candidate is not preparing. */
export function prepLeftMs(state: AgentState | null, now: number): number | null {
  if (state?.prepMsLeft == null) return null;
  return Math.max(0, state.prepMsLeft - Math.max(0, now - state.receivedAt));
}
