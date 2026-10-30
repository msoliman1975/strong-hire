/**
 * Round 3 explainability and motion (canvas board R3 Explain), with `v2_enabled` on: the ⓘ
 * explainers, "Get started in 3 steps", the once-only tour, the How it works page, a teaching
 * empty state, and motion that stays off with reduced motion.
 */
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "./App";
import { EXPLAIN, Explain } from "./components/Explain";
import { TOUR_REPLAY_EVENT } from "./components/Tour";
import { mockStore } from "./mocks/node";
import { resetMockStories } from "./mocks/storyHandlers";
import { setFeatureOverrides } from "./theme/features";

const styles = readFileSync(join(resolve(__dirname), "styles.css"), "utf8");

const USER_ID = "00000000-0000-4000-8000-0000000000a1";

beforeEach(() => {
  globalThis.localStorage?.clear();
  // Most tests here are not about the tour: mark it seen.
  globalThis.localStorage?.setItem(`sh-tour-done-${USER_ID}`, "x");
});
afterEach(() => setFeatureOverrides({}));

function signedIn() {
  const email = "ana@example.com";
  mockStore.db.users[email] = {
    id: USER_ID,
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

function renderApp(path: string) {
  signedIn();
  setFeatureOverrides({ v2_enabled: true });
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

describe("explainers", () => {
  it("UI-1: an ⓘ opens one plain sentence, named for what it explains", async () => {
    const user = userEvent.setup();
    render(<Explain topic="Readiness">{EXPLAIN.readiness}</Explain>);
    const toggle = screen.getByText("i").closest("summary") as HTMLElement;
    expect(toggle).toHaveAttribute("aria-label", "What's this: Readiness");
    await user.click(toggle);
    expect(screen.getByRole("note")).toHaveTextContent("It counts nothing from Practice mode");
  });

  it("RD-3: the readiness, takes, Proven and hire-signal sentences keep the practice-estimate framing", () => {
    expect(EXPLAIN.readiness).toMatch(/practice estimate, not a prediction/);
    expect(EXPLAIN.hireSignal).toMatch(/practice estimate, not a prediction/);
    expect(EXPLAIN.proven).toMatch(/Realistic rehearsal/);
    expect(EXPLAIN.takes).toMatch(/1 to 4/);
  });
});

describe("tour", () => {
  it("UI-2: a 3-step tour shows once on the first visit, and Skip ends it for good", async () => {
    globalThis.localStorage?.removeItem(`sh-tour-done-${USER_ID}`);
    const user = renderApp("/");
    const tour = await screen.findByRole("dialog", { name: "Your menu" });
    expect(tour).toHaveTextContent("1 of 3");
    await user.click(within(tour).getByRole("button", { name: "Next tip" }));
    expect(screen.getByRole("dialog", { name: "Career Stories with Strova" })).toHaveTextContent("2 of 3");
    await user.click(screen.getByRole("button", { name: "Skip the tour" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();
    renderApp("/");
    await screen.findByRole("heading", { level: 1, name: /^Good / });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("UI-2: Replay the tour starts it again", async () => {
    renderApp("/");
    await screen.findByRole("heading", { level: 1, name: /^Good / });
    act(() => {
      window.dispatchEvent(new Event(TOUR_REPLAY_EVENT));
    });
    expect(await screen.findByRole("dialog", { name: "Your menu" })).toBeInTheDocument();
  });
});

describe("How it works", () => {
  it("UI-2: the avatar menu links to How it works, which explains the modes and offers the tour", async () => {
    const user = renderApp("/");
    const bar = await screen.findByRole("banner", { name: "Top bar" });
    await user.click(within(bar).getByRole("button", { name: "Account menu" }));
    await user.click(within(bar).getByRole("link", { name: "Help and how it works" }));
    expect(await screen.findByRole("heading", { level: 1, name: "How it works" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Practice mode and Realistic mode" })).toBeInTheDocument();
    expect(screen.getByText(/Your audio is never stored/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replay the tour" })).toBeInTheDocument();
  });
});

describe("teaching empty states", () => {
  it("ST-3: an empty studio says what a story is, with one button to start", async () => {
    resetMockStories([]);
    renderApp("/stories");
    const empty = await screen.findByTestId("stories-empty");
    expect(empty).toHaveTextContent("A story is one moment from your career, told in 5 parts");
    expect(within(empty).getByRole("link", { name: "Build my first story" })).toHaveAttribute("href", "/coach/new");
  });
});

describe("motion", () => {
  it("UI-1: every R3 animation sits inside prefers-reduced-motion: no-preference, at 400 ms or less", () => {
    const section = styles.slice(styles.indexOf("R3 motion"));
    const media = section.indexOf("@media (prefers-reduced-motion: no-preference)");
    const keyframes = section.indexOf("@keyframes");
    expect(media).toBeGreaterThan(0);
    const before = section.slice(0, media);
    expect(before).not.toMatch(/animation:/);
    const block = section.slice(media, keyframes);
    const durations = [...block.matchAll(/animation:\s*[\w-]+\s+(\d+)ms/g)].map((m) => Number(m[1]));
    expect(durations.length).toBeGreaterThan(5);
    // The mic pulse loops over 1.6 s but moves only in its first quarter (400 ms).
    for (const d of durations) expect(d === 1600 || (d >= 150 && d <= 400)).toBe(true);
    // Nothing in the live room.
    expect(block).not.toMatch(/\.room|\.live\b|live__/);
  });
});
