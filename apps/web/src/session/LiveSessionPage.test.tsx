/** The live session page (P10): mic check, joining, phase and timer, Coach controls, reconnect (IV-9). */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionRecord, VoiceJoin } from "../api/types";
import { createQueryClient } from "../App";
import { server } from "../mocks/node";
import { AGENT_WAIT_MS, LiveSessionPage } from "./LiveSessionPage";
import { MOCK_VOICE_URL, parseAgentActivity, parseAgentMessage, parseInterviewerVoice, remainingMs, type AgentCommand, type VoiceHandlers } from "./voice";

const voice = vi.hoisted(() => ({
  handlers: null as VoiceHandlers | null,
  sent: [] as string[],
  micError: null as Error | null,
}));

vi.mock("./microphone", async (original) => ({
  ...(await original<typeof import("./microphone")>()),
  openMicrophone: async () => {
    if (voice.micError) throw voice.micError;
    return { level: () => 0.5, stop: () => undefined };
  },
}));

vi.mock("./mockVoice", () => ({
  connectMockVoice: async (_join: VoiceJoin, handlers: VoiceHandlers) => {
    voice.handlers = handlers;
    handlers.onConnection("connected");
    return {
      send: async (command: AgentCommand) => {
        voice.sent.push(command);
      },
      disconnect: async () => undefined,
    };
  },
}));

afterEach(() => {
  voice.handlers = null;
  voice.sent = [];
  voice.micError = null;
  vi.useRealTimers();
});

function session(changes: Partial<SessionRecord> = {}): SessionRecord {
  return {
    id: "s1",
    job_target_id: "j1",
    resume_id: null,
    config: { interview_type: "behavioral", difficulty: "realistic", mode: "coach", duration_min: 30, level: "senior" },
    channel: "voice",
    status: "created",
    brief_ready: true,
    started_at: null,
    ended_at: null,
    minutes_billed: 0,
    failure_reason: null,
    ...changes,
  };
}

function renderLive(record: SessionRecord) {
  const joins: string[] = [];
  server.use(
    http.get("*/api/sessions/:sessionId", () => HttpResponse.json(record)),
    http.post("*/api/sessions/:sessionId/voice/join", ({ params }) => {
      joins.push(String(params.sessionId));
      const join: VoiceJoin = { livekit_url: MOCK_VOICE_URL, room: "session-s1", token: "t", identity: "candidate-u" };
      return HttpResponse.json(join);
    }),
    http.post("*/api/sessions/:sessionId/end", () => HttpResponse.json({ ...record, status: "scoring" })),
  );
  const user = userEvent.setup(vi.isFakeTimers() ? { advanceTimers: (ms) => vi.advanceTimersByTime(ms) } : {});
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s1/live"]}>
        <Routes>
          <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
          <Route path="/sessions/:sessionId/debrief" element={<h1>Debrief page</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, joins };
}

async function joinRoom(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Check my microphone" }));
  expect(await screen.findByText("We can hear you.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Join the interview" }));
  await screen.findByText("Waiting for the interviewer to join");
}

const say = (phase: "intro" | "core", said: string[], paused = false, elapsedMs = 60_000) =>
  act(() => voice.handlers!.onState({ phase, paused, elapsedMs, said, receivedAt: Date.now() }));

describe("live session page", () => {
  it("shows a clear message when the browser blocks the microphone", async () => {
    voice.micError = new DOMException("denied", "NotAllowedError");
    const { user, joins } = renderLive(session());
    await user.click(await screen.findByRole("button", { name: "Check my microphone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your browser blocked the microphone.");
    expect(joins).toEqual([]); // the session did not start, so no minute is billed
  });

  it("stops waiting when the plan could not be built, and offers to try again", async () => {
    const reason = "We could not prepare your interviewer. Nothing was counted or billed. Start a new interview to try again.";
    const created: unknown[] = [];
    const { user } = renderLive(session({ status: "failed", brief_ready: false, failure_reason: reason }));
    server.use(
      http.post("*/api/sessions", async ({ request }) => {
        created.push(await request.json());
        return HttpResponse.json(session({ id: "s2" }), { status: 201 });
      }),
      http.get("*/api/sessions/s2", () => HttpResponse.json(session({ id: "s2" }))),
    );
    expect(await screen.findByTestId("not-started")).toHaveTextContent(reason);
    expect(screen.queryByText(/Preparing your interviewer/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Check my microphone" })).toBeInTheDocument();
    expect(created).toEqual([{ job_target_id: "j1", config: session().config, channel: "voice" }]);
  });

  it("waits for the interview plan before the candidate can join", async () => {
    const { user } = renderLive(session({ brief_ready: false }));
    await user.click(await screen.findByRole("button", { name: "Check my microphone" }));
    expect(await screen.findByText(/Preparing your interviewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join the interview" })).toBeDisabled();
  });

  it("IV-8: joins, shows the phase, captions and timer, and sends Coach commands", async () => {
    const { user, joins } = renderLive(session());
    await joinRoom(user);
    expect(joins).toEqual(["s1"]);
    act(() => voice.handlers!.onAgentJoined());
    say("core", ["Tell me about a time you disagreed with your manager."]);
    expect(screen.getByTestId("captions")).toHaveTextContent("Tell me about a time you disagreed");
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Core questions");
    expect(screen.getByTestId("timer")).toHaveTextContent(/^(29:00|28:59)$/);

    await user.click(screen.getByRole("button", { name: "Ask for a hint" }));
    await user.click(screen.getByRole("button", { name: "Redo my answer" }));
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(voice.sent).toEqual(["hint", "redo", "pause"]);
    say("core", [], true);
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask for a hint" })).toBeDisabled();
  });

  it("IV-10: the avatar shows when the interviewer speaks and listens", async () => {
    const { user } = renderLive(session());
    await joinRoom(user);
    expect(screen.getByTestId("interviewer-avatar")).toHaveTextContent("Interviewer: Joining");
    act(() => voice.handlers!.onAgentJoined());
    act(() => voice.handlers!.onActivity("speaking"));
    expect(screen.getByTestId("interviewer-avatar")).toHaveTextContent("Interviewer: Speaking");
    act(() => voice.handlers!.onActivity("listening"));
    expect(screen.getByTestId("interviewer-avatar")).toHaveAttribute("data-activity", "listening");
  });

  it("Realistic mode has no Coach controls", async () => {
    const realistic = session({ config: { ...session().config, mode: "realistic" } });
    const { user } = renderLive(realistic);
    await joinRoom(user);
    act(() => voice.handlers!.onAgentJoined());
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask for a hint" })).not.toBeInTheDocument();
  });

  it("IV-9: shows a reconnect banner, and Rejoin joins the same session again", async () => {
    const { user, joins } = renderLive(session());
    await joinRoom(user);
    act(() => voice.handlers!.onAgentJoined());
    act(() => voice.handlers!.onConnection("reconnecting"));
    expect(screen.getByTestId("reconnect-banner")).toHaveTextContent("Your interview clock is stopped.");
    act(() => voice.handlers!.onConnection("disconnected"));
    await user.click(screen.getByRole("button", { name: "Rejoin" }));
    await screen.findByText("Waiting for the interviewer to join");
    expect(joins).toEqual(["s1", "s1"]);
  });

  it("says so when the interviewer does not join", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { user } = renderLive(session());
    await joinRoom(user);
    act(() => vi.advanceTimersByTime(10_100));
    expect(screen.getByText("The interviewer is starting. This can take up to a minute.")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(AGENT_WAIT_MS));
    expect(await screen.findByRole("alert")).toHaveTextContent("The interviewer did not join.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("the end of the session opens the debrief page", async () => {
    const { user } = renderLive(session());
    await joinRoom(user);
    act(() => voice.handlers!.onEnded());
    expect(await screen.findByRole("heading", { name: "Debrief page" })).toBeInTheDocument();
  });

  it("End interview tells the agent and ends the session in the API", async () => {
    const { user } = renderLive(session());
    await joinRoom(user);
    act(() => voice.handlers!.onAgentJoined());
    await user.click(screen.getByRole("button", { name: "End interview" }));
    const dialog = screen.getByRole("dialog", { name: "End the interview?" });
    await user.click(dialog.querySelector(".btn--danger") as HTMLElement);
    expect(await screen.findByRole("heading", { name: "Debrief page" })).toBeInTheDocument();
    expect(voice.sent).toEqual(["end"]);
  });
});

describe("agent messages", () => {
  it("IV-10: reads the interviewer voice, and ignores anything else", () => {
    expect(parseInterviewerVoice("male")).toBe("male");
    expect(parseInterviewerVoice("female")).toBe("female");
    expect(parseInterviewerVoice("robot")).toBeNull();
    expect(parseInterviewerVoice(undefined)).toBeNull();
  });

  it("IV-10: reads the LiveKit agent state, and unknown states are idle", () => {
    expect(parseAgentActivity("speaking")).toBe("speaking");
    expect(parseAgentActivity("thinking")).toBe("thinking");
    expect(parseAgentActivity("initializing")).toBe("idle");
    expect(parseAgentActivity(undefined)).toBe("idle");
  });

  it("reads state and ended messages, and ignores anything else", () => {
    const bytes = (v: unknown) => new TextEncoder().encode(JSON.stringify(v));
    const state = parseAgentMessage(
      bytes({ type: "state", phase: "core", paused: false, elapsed_ms: 1000, said: ["Hi", 3] }),
      5,
    );
    expect(state).toEqual({
      type: "state",
      state: { phase: "core", paused: false, elapsedMs: 1000, said: ["Hi"], receivedAt: 5 },
    });
    expect(parseAgentMessage(bytes({ type: "ended" }))).toEqual({ type: "ended" });
    expect(parseAgentMessage(bytes({ type: "other" }))).toBeNull();
    expect(parseAgentMessage(new TextEncoder().encode("not json"))).toBeNull();
  });

  it("the timer counts down from the agent's clock and stops while paused", () => {
    const base = { phase: "core" as const, said: [], receivedAt: 0 };
    expect(remainingMs(30, null, 0)).toBe(1_800_000);
    expect(remainingMs(30, { ...base, paused: false, elapsedMs: 60_000 }, 10_000)).toBe(1_730_000);
    expect(remainingMs(30, { ...base, paused: true, elapsedMs: 60_000 }, 10_000)).toBe(1_740_000);
  });
});
