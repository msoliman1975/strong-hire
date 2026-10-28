/**
 * The coach session's voice channel (CO-6). The voice agent (apps/voice, coach_agent.py) runs
 * the coach on the interview's voice loop; this hook joins its room and carries its messages to
 * the coach page. The page owns the layout: the mic button calls `start`, "Record a take" calls
 * `startTake` and `endTake`.
 *
 * Agent to browser, data topic "session":
 *   {"type": "coach_turn", "said": [lines], "result": CoachTurnResult | null}
 *   {"type": "take", "recording": bool}
 *   {"type": "take_done", "text", "duration_s"}   one spoken take, transcript only (no audio)
 *   {"type": "ended"}
 * Browser to agent, data topic "coach": {"command": "end" | "take_start" | "take_end" | "take_cancel"}.
 *
 * A finished take goes to `onTake`; the page sends it to the take scoring (CO-7, S33) like a
 * typed take, with channel "voice".
 */
import { RemoteParticipant, Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

import { request } from "../../api/client";
import type { VoiceJoin } from "../../api/types";
import type { components } from "../../api/schema.gen";
import {
  AGENT_STATE_ATTRIBUTE,
  COACH_TOPIC,
  SESSION_TOPIC,
  isMockVoice,
  parseAgentActivity,
  type AgentActivity,
  type ConnectionState,
} from "../../session/voice";

export type CoachTurnResult = components["schemas"]["CoachTurnResult"];

export type CoachVoiceCommand = "end" | "take_start" | "take_end" | "take_cancel";

/** One spoken telling of the story (CO-6, CO-7). Only the transcript leaves the room. */
export interface VoiceTake {
  text: string;
  durationS: number;
}

export type CoachMessage =
  | { type: "coach_turn"; said: string[]; result: CoachTurnResult | null }
  | { type: "take"; recording: boolean }
  | { type: "take_done"; take: VoiceTake }
  | { type: "ended" };

/** Reads one agent message. Unknown or broken messages return null. */
export function parseCoachMessage(data: Uint8Array): CoachMessage | null {
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder().decode(data));
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null) return null;
  const m = raw as Record<string, unknown>;
  switch (m.type) {
    case "ended":
      return { type: "ended" };
    case "take":
      return { type: "take", recording: m.recording === true };
    case "take_done":
      if (typeof m.text !== "string" || !m.text.trim()) return null;
      return {
        type: "take_done",
        take: { text: m.text, durationS: typeof m.duration_s === "number" ? m.duration_s : 0 },
      };
    case "coach_turn": {
      const said = Array.isArray(m.said) ? m.said.filter((s): s is string => typeof s === "string") : [];
      const result = typeof m.result === "object" && m.result !== null ? (m.result as CoachTurnResult) : null;
      return { type: "coach_turn", said, result };
    }
    default:
      return null;
  }
}

export const encodeCoachCommand = (command: CoachVoiceCommand) => new TextEncoder().encode(JSON.stringify({ command }));

export interface CoachVoiceHandlers {
  onMessage: (message: CoachMessage) => void;
  onConnection: (state: ConnectionState) => void;
  onActivity: (activity: AgentActivity) => void;
}

export interface CoachVoiceConnection {
  send: (command: CoachVoiceCommand) => Promise<void>;
  disconnect: () => Promise<void>;
}

export type CoachVoiceConnector = (join: VoiceJoin, handlers: CoachVoiceHandlers) => Promise<CoachVoiceConnection>;

/** The real room: the microphone goes in, the coach's audio plays. Audio is never recorded. */
export const connectCoachLiveKit: CoachVoiceConnector = async (join, handlers) => {
  const room = new Room({ adaptiveStream: true, dynacast: true });
  const audio: HTMLMediaElement[] = [];
  let leaving = false;
  const activity = (p: RemoteParticipant) => {
    if (p.isAgent) handlers.onActivity(parseAgentActivity(p.attributes[AGENT_STATE_ATTRIBUTE]));
  };
  room
    .on(RoomEvent.ParticipantConnected, activity)
    .on(RoomEvent.ParticipantAttributesChanged, (_changed, p) => {
      if (p instanceof RemoteParticipant) activity(p);
    })
    .on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== SESSION_TOPIC) return;
      const message = parseCoachMessage(payload);
      if (message) handlers.onMessage(message);
    })
    .on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind !== Track.Kind.Audio) return;
      const element = track.attach();
      element.hidden = true;
      document.body.appendChild(element);
      audio.push(element);
    })
    .on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((e) => e.remove());
    })
    .on(RoomEvent.Reconnecting, () => handlers.onConnection("reconnecting"))
    .on(RoomEvent.Reconnected, () => handlers.onConnection("connected"))
    .on(RoomEvent.Disconnected, () => {
      audio.splice(0).forEach((e) => e.remove());
      handlers.onActivity("idle");
      if (!leaving) handlers.onConnection("disconnected");
    });

  await room.connect(join.livekit_url, join.token);
  await room.startAudio(); // the user clicked the mic button, so the browser lets audio play
  await room.localParticipant.setMicrophoneEnabled(true, { echoCancellation: true, noiseSuppression: true });
  room.remoteParticipants.forEach(activity);
  handlers.onConnection("connected");
  return {
    send: (command) =>
      room.localParticipant.publishData(encodeCoachCommand(command), { reliable: true, topic: COACH_TOPIC }),
    disconnect: async () => {
      leaving = true;
      await room.disconnect();
    },
  };
};

export const MOCK_COACH_OPENER = "Tell me about one time you led a hard change. Where were you working?";
export const MOCK_TAKE_TEXT = "We cut deploys from forty minutes to six. I owned the rollout.";

/** A room without LiveKit, for the browser mocks and tests: the coach says its first line, and a
 * take returns a fixed transcript. */
export const connectCoachMockVoice: CoachVoiceConnector = async (_join, handlers) => {
  let open = true;
  let recording = false;
  handlers.onConnection("connected");
  setTimeout(() => {
    if (open) handlers.onMessage({ type: "coach_turn", said: [MOCK_COACH_OPENER], result: null });
  }, 0);
  return {
    send: async (command) => {
      if (!open) return;
      if (command === "end") {
        open = false;
        handlers.onMessage({ type: "ended" });
      } else if (command === "take_start" && !recording) {
        recording = true;
        handlers.onMessage({ type: "take", recording: true });
      } else if ((command === "take_end" || command === "take_cancel") && recording) {
        recording = false;
        if (command === "take_end") handlers.onMessage({ type: "take_done", take: { text: MOCK_TAKE_TEXT, durationS: 42 } });
        handlers.onMessage({ type: "take", recording: false });
      }
    },
    disconnect: async () => {
      open = false;
      handlers.onActivity("idle");
    },
  };
};

/** The coach room's LiveKit token (CO-6, POST /coach/sessions/{id}/voice/join). */
export const joinCoachVoice = (sessionId: string) =>
  request<VoiceJoin>("POST", `/coach/sessions/${encodeURIComponent(sessionId)}/voice/join`);

export type CoachVoiceStatus = "idle" | "connecting" | "live" | "reconnecting" | "ended" | "error";

export interface UseCoachVoiceOptions {
  /** A finished spoken take, for the take scoring (CO-7). */
  onTake?: (take: VoiceTake) => void;
  /** After each coach turn; `result` carries the story's parts (CO-3) once the API answered. */
  onTurn?: (said: string[], result: CoachTurnResult | null) => void;
  onEnded?: () => void;
  join?: (sessionId: string) => Promise<VoiceJoin>;
  connect?: CoachVoiceConnector;
}

export interface CoachVoice {
  status: CoachVoiceStatus;
  activity: AgentActivity;
  recording: boolean;
  /** The coach's lines said by voice, oldest first. */
  said: string[];
  error: string | null;
  start: () => Promise<void>;
  end: () => Promise<void>;
  startTake: () => Promise<void>;
  endTake: () => Promise<void>;
  cancelTake: () => Promise<void>;
}

export function useCoachVoice(sessionId: string, options: UseCoachVoiceOptions = {}): CoachVoice {
  const [status, setStatus] = useState<CoachVoiceStatus>("idle");
  const [activity, setActivity] = useState<AgentActivity>("idle");
  const [recording, setRecording] = useState(false);
  const [said, setSaid] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const connection = useRef<CoachVoiceConnection | null>(null);
  const latest = useRef(options);
  useEffect(() => {
    latest.current = options;
  });

  useEffect(
    () => () => {
      void connection.current?.disconnect();
      connection.current = null;
    },
    [],
  );

  const start = useCallback(async () => {
    if (connection.current) return;
    setStatus("connecting");
    setError(null);
    try {
      const join = await (latest.current.join ?? joinCoachVoice)(sessionId);
      const connect = latest.current.connect ?? (isMockVoice(join.livekit_url) ? connectCoachMockVoice : connectCoachLiveKit);
      connection.current = await connect(join, {
        onConnection: (state) => setStatus(state === "connected" ? "live" : state === "reconnecting" ? "reconnecting" : "ended"),
        onActivity: setActivity,
        onMessage: (message) => {
          if (message.type === "coach_turn") {
            if (message.said.length) setSaid((lines) => [...lines, ...message.said]);
            latest.current.onTurn?.(message.said, message.result);
          } else if (message.type === "take") {
            setRecording(message.recording);
          } else if (message.type === "take_done") {
            latest.current.onTake?.(message.take);
          } else {
            setStatus("ended");
            setRecording(false);
            void connection.current?.disconnect();
            connection.current = null;
            latest.current.onEnded?.();
          }
        },
      });
    } catch (err) {
      connection.current = null;
      setStatus("error");
      setError(err instanceof Error ? err.message : "Could not start the voice session.");
    }
  }, [sessionId]);

  const send = useCallback(async (command: CoachVoiceCommand) => {
    await connection.current?.send(command);
  }, []);

  return {
    status,
    activity,
    recording,
    said,
    error,
    start,
    end: useCallback(() => send("end"), [send]),
    startTake: useCallback(() => send("take_start"), [send]),
    endTake: useCallback(() => send("take_end"), [send]),
    cancelTake: useCallback(() => send("take_cancel"), [send]),
  };
}
