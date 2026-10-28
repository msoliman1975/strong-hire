import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  MOCK_COACH_OPENER,
  MOCK_TAKE_TEXT,
  encodeCoachCommand,
  parseCoachMessage,
  useCoachVoice,
  type CoachVoiceConnector,
} from "./useCoachVoice";

const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));

describe("CO-6 coach voice messages", () => {
  it("reads the coach agent's messages and drops broken ones", () => {
    expect(parseCoachMessage(encode({ type: "coach_turn", said: ["Hi.", 3], result: null }))).toEqual({
      type: "coach_turn",
      said: ["Hi."],
      result: null,
    });
    expect(parseCoachMessage(encode({ type: "take", recording: true }))).toEqual({ type: "take", recording: true });
    expect(parseCoachMessage(encode({ type: "take_done", text: "I led it.", duration_s: 12.5 }))).toEqual({
      type: "take_done",
      take: { text: "I led it.", durationS: 12.5 },
    });
    expect(parseCoachMessage(encode({ type: "take_done", text: " " }))).toBeNull();
    expect(parseCoachMessage(encode({ type: "ended" }))).toEqual({ type: "ended" });
    expect(parseCoachMessage(encode({ type: "state" }))).toBeNull();
    expect(parseCoachMessage(new TextEncoder().encode("{nope"))).toBeNull();
  });

  it("sends commands on the coach topic as JSON", () => {
    expect(JSON.parse(new TextDecoder().decode(encodeCoachCommand("take_start")))).toEqual({ command: "take_start" });
  });
});

describe("CO-6 useCoachVoice", () => {
  it("joins the coach room through the mocked join and hears the coach", async () => {
    const onTurn = vi.fn();
    const { result } = renderHook(() => useCoachVoice("abc", { onTurn }));
    await act(() => result.current.start());
    await waitFor(() => expect(result.current.said).toEqual([MOCK_COACH_OPENER]));
    expect(result.current.status).toBe("live");
    expect(onTurn).toHaveBeenCalledWith([MOCK_COACH_OPENER], null);
  });

  it("records a spoken take and hands its transcript to the take scoring", async () => {
    const onTake = vi.fn();
    const { result } = renderHook(() => useCoachVoice("abc", { onTake }));
    await act(() => result.current.start());
    await act(() => result.current.startTake());
    expect(result.current.recording).toBe(true);
    await act(() => result.current.endTake());
    expect(result.current.recording).toBe(false);
    expect(onTake).toHaveBeenCalledWith({ text: MOCK_TAKE_TEXT, durationS: 42 });
  });

  it("ends when the candidate ends the session", async () => {
    const onEnded = vi.fn();
    const { result } = renderHook(() => useCoachVoice("abc", { onEnded }));
    await act(() => result.current.start());
    await act(() => result.current.end());
    expect(result.current.status).toBe("ended");
    expect(onEnded).toHaveBeenCalledOnce();
  });

  it("passes the coach's turn result on, so the story's parts update (CO-3)", async () => {
    const connect: CoachVoiceConnector = async (_join, handlers) => {
      handlers.onConnection("connected");
      handlers.onMessage({ type: "coach_turn", said: ["What was at stake?"], result: { ended: false } as never });
      return { send: async () => {}, disconnect: async () => {} };
    };
    const onTurn = vi.fn();
    const { result } = renderHook(() => useCoachVoice("abc", { onTurn, connect }));
    await act(() => result.current.start());
    expect(onTurn).toHaveBeenCalledWith(["What was at stake?"], { ended: false });
  });

  it("shows an error when the join fails", async () => {
    const join = () => Promise.reject(new Error("Voice is paused."));
    const { result } = renderHook(() => useCoachVoice("abc", { join }));
    await act(() => result.current.start());
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Voice is paused.");
  });
});
