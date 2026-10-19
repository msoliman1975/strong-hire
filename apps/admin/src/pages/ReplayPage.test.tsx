/** Replay (SM-7 to SM-11, SM-16) against the admin mocks. jsdom has no media playback or Web
 * Audio, so play() is stubbed and the tests drive the time through the audio element's events. */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { latencyLevel, lineAt, splitTimes } from "../api/sim";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";
import { MOCK_SIM_SESSION, mockReplay, simState } from "../mocks/simHandlers";

function signInAdmin() {
  mockStore.db.users["admin@example.com"] = {
    id: "00000000-0000-4000-8000-0000000000a9",
    org_id: "00000000-0000-4000-8000-0000000000b9",
    email: "admin@example.com",
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: null,
    profile_complete: true,
  };
  mockSignIn(mockStore, "admin@example.com");
}

function renderAt(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

async function openReplay(sessionId = MOCK_SIM_SESSION) {
  signInAdmin();
  const user = renderAt(`/simulations/replay/${sessionId}`);
  expect(await screen.findByRole("heading", { name: "Replay", level: 1 })).toBeInTheDocument();
  return user;
}

function audio(): HTMLAudioElement {
  const el = document.querySelector("audio");
  if (!el) throw new Error("no audio element");
  return el;
}

/** Moves the player to `ms` the way the browser does: currentTime, then timeupdate. */
function playTo(ms: number) {
  act(() => {
    Object.defineProperty(audio(), "currentTime", { value: ms / 1000, configurable: true, writable: true });
    fireEvent(audio(), new Event("timeupdate"));
  });
}

function currentLine(): HTMLElement | null {
  return document.querySelector('li[aria-current="true"]');
}

let played: number;

beforeEach(() => {
  played = 0;
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    played += 1;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("pause"));
  });
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => played === 0);
});

afterEach(() => vi.restoreAllMocks());

describe("replay helpers", () => {
  it("SM-9: response time colors", () => {
    expect(latencyLevel(799)).toBe("ok");
    expect(latencyLevel(800)).toBe("slow");
    expect(latencyLevel(1500)).toBe("slow");
    expect(latencyLevel(1501)).toBe("bad");
  });

  it("SM-10: finds mm:ss in judge text", () => {
    expect(splitTimes("Asked at 00:21 and 1:05.")).toEqual([
      "Asked at ",
      { text: "00:21", ms: 21_000 },
      " and ",
      { text: "1:05", ms: 65_000 },
      ".",
    ]);
  });

  it("SM-8: the line at a time is the last one started", () => {
    expect(lineAt(mockReplay.lines, 0)).toBe(-1);
    expect(lineAt(mockReplay.lines, 5_000)).toBe(1);
    expect(lineAt(mockReplay.lines, 99_000)).toBe(6);
  });
});

describe("Replay page", () => {
  it("SM-7, SM-9: player with speed, channels and markers; chips and p50/p90 in the header", async () => {
    await openReplay();
    expect(audio()).toHaveAttribute("src", expect.stringContaining(`/admin/sessions/${MOCK_SIM_SESSION}/audio`));
    expect(screen.getByRole("group", { name: "Speed" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Channels" })).getByRole("button", { name: "Mixed" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Slow turn at 0:31" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Judge: Repeated the question at 0:31/ })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("1200 ms");
    expect(summary).toHaveTextContent("2000 ms");
    expect(summary).toHaveTextContent("1 of 3");
    const chips = document.querySelectorAll(".latency");
    expect([...chips].map((c) => c.getAttribute("data-level"))).toEqual(["ok", "slow", "bad"]);
    expect(screen.queryByText(/Times are approximate/)).not.toBeInTheDocument();
  });

  it("SM-8: the playing line is highlighted; clicking a time seeks and plays", async () => {
    const user = await openReplay();
    playTo(10_000);
    expect(currentLine()).toHaveTextContent("I led the billing rebuild.");
    await user.click(screen.getByRole("button", { name: "0:21" }));
    expect(currentLine()).toHaveTextContent("What went wrong?");
    expect(played).toBe(1);
  });

  it("SM-8: keys J, K, N and space", async () => {
    const user = await openReplay();
    playTo(4_500);
    await user.keyboard("k");
    expect(currentLine()).toHaveTextContent("Tell me about a project");
    await user.keyboard("j");
    expect(currentLine()).toHaveTextContent("Happy to be here.");
    await user.keyboard("n");
    expect(currentLine()).toHaveTextContent("Take your time.");
    await user.keyboard(" ");
    expect(played).toBe(1);
  });

  it("SM-8: scrolling the transcript by hand stops following until Follow", async () => {
    const user = await openReplay();
    fireEvent.wheel(document.querySelector(".replay-transcript") as Element);
    const follow = screen.getByRole("button", { name: "Follow" });
    await user.click(follow);
    expect(screen.queryByRole("button", { name: "Follow" })).not.toBeInTheDocument();
  });

  it("SM-10, SM-11: judge verdicts with time links, and the scorecard", async () => {
    const user = await openReplay();
    const judge = screen.getByRole("region", { name: "Judge" });
    expect(within(judge).getByText("fail")).toBeInTheDocument();
    expect(within(judge).getByText("n/a")).toBeInTheDocument();
    await user.click(within(judge).getAllByRole("button", { name: "00:31" })[0]);
    expect(currentLine()).toHaveTextContent("Take your time.");
    const card = screen.getByRole("region", { name: "Scorecard" });
    expect(card).toHaveTextContent("Lean Hire");
    expect(card).toHaveTextContent("ownership 3 / 4");
  });

  it("SM-8: an older or text run has approximate times and no player", async () => {
    const state = simState(mockStore.db);
    state.replays["text-run"] = {
      ...structuredClone(mockReplay),
      session_id: "text-run",
      channel: "text",
      timing: "approximate",
      audio: { available: false, bytes: null },
      judge: null,
      scorecard: null,
    };
    await openReplay("text-run");
    expect(screen.getByText(/Times are approximate/)).toBeInTheDocument();
    expect(screen.getByText("A text interview: no recording.")).toBeInTheDocument();
    expect(document.querySelector("audio")).toBeNull();
    expect(screen.getByText(/Not judged/)).toBeInTheDocument();
  });

  it("SM-16: a replay that does not exist is an error, not a blank page", async () => {
    await openReplay("00000000-0000-4000-8000-000000000999").catch(() => undefined);
    expect(await screen.findByText("The replay could not be loaded.")).toBeInTheDocument();
  });
});
