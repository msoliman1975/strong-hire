/**
 * CO-2, CO-7 and CO-8 (UI): the coach session page and the workbench's takes and versions, with
 * MSW (mocks/coachHandlers.ts, the shapes of strong_api.coach and strong_api.takes).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { mockTakes, resetMockCoach, scriptMockCoach } from "../../mocks/coachHandlers";
import { server } from "../../mocks/node";
import { mockStory, mockStoryLibrary, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { StoryWorkbenchPage } from "../stories/StoryWorkbenchPage";
import { V2Only } from "../stories/V2Only";
import { CoachSessionPage } from "./CoachSessionPage";
import { CoachStartPage } from "./CoachStartPage";

const STORY = mockStory({
  id: "s1",
  title: "Checkout migration",
  context: "Payments service nobody owned.",
  action: "I wrote the migration plan.",
  skills: ["ownership", "impact"],
});

const BARE = mockStory({ id: "s2", title: "No skills yet", context: "A thing happened." });

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories([STORY, BARE]);
  resetMockCoach();
});
afterEach(() => setFeatureOverrides({}));

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderAt(path: string, { voiceReady = false } = {}) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<p>Home</p>} />
          <Route path="/stories" element={<p>Stories</p>} />
          <Route path="/stories/:storyId" element={<V2Only><StoryWorkbenchPage /></V2Only>} />
          <Route path="/coach/new" element={<V2Only><CoachStartPage /></V2Only>} />
          <Route path="/coach/:sessionId" element={<V2Only><CoachSessionPage voiceReady={voiceReady} /></V2Only>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const parts = () =>
  Object.fromEntries(screen.getAllByTestId("coach-part").map((li) => [li.dataset.part, li.dataset.state]));

describe("coach session", () => {
  it("CO-2: a missing skill starts a coach session for it, and the coach opens", async () => {
    const started: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/coach/sessions")) started.push(await request.clone().json());
    });
    renderAt("/coach/new?skill=conflict_handling&job=j1");
    expect(await screen.findByRole("heading", { level: 1, name: "Build a story" })).toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toMatch(/^\/coach\/[0-9a-f-]{36}$/);
    expect(started).toEqual([
      { style: "gentle", channel: "text", story_id: null, target_skill: "conflict_handling", job_target_id: "j1" },
    ]);
    const turns = screen.getAllByTestId("coach-turn");
    expect(turns).toHaveLength(1);
    expect(turns[0]).toHaveTextContent("Let's build one story that shows conflict handling");
    expect(screen.getByRole("list", { name: "Skills this story could prove" })).toHaveTextContent("Conflict handling");
    expect(parts()).toEqual({ context: "now", stakes: "next", action: "next", result: "next", reflection: "next" });
    expect(screen.getByTestId("coach-missing")).toHaveTextContent(
      "Still missing: Context, Stakes, Your action, Result, Reflection",
    );
  });

  it("CO-2, CO-3: each turn adds to the conversation and the story takes shape beside it", async () => {
    const user = userEvent.setup();
    scriptMockCoach([
      { parts: { context: "The platform team wanted us to wait a quarter." }, message: "Why did it matter?", skills: ["conflict_handling", "collaboration"] },
    ]);
    renderAt("/coach/new");
    await screen.findByRole("heading", { level: 1, name: "Build a story" });

    await user.type(screen.getByRole("textbox", { name: "Your reply" }), "The platform team wanted us to wait a quarter.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const log = screen.getByRole("log", { name: "Conversation with your coach" });
    expect(await within(log).findByText("Why did it matter?")).toBeInTheDocument();
    expect(within(log).getAllByTestId("coach-turn").map((t) => t.dataset.speaker)).toEqual(["coach", "candidate", "coach"]);
    expect(screen.getByRole("textbox", { name: "Your reply" })).toHaveValue("");
    expect(parts()).toMatchObject({ context: "done", stakes: "now" });
    expect(screen.getByRole("list", { name: "Story parts" })).toHaveTextContent("The platform team wanted us to wait a quarter.");
    expect(screen.getByTestId("coach-missing")).not.toHaveTextContent("Context");
    const prove = screen.getByRole("list", { name: "Skills this story could prove" });
    expect(within(prove).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Conflict handling", "Collaboration"]);
  });

  it("CO-5: the style switch changes the coaching style", async () => {
    const user = userEvent.setup();
    const styles: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.url.endsWith("/style")) styles.push(await request.clone().json());
    });
    renderAt("/coach/new");
    const group = await screen.findByRole("group", { name: "Coaching style" });
    expect(within(group).getByRole("button", { name: "Gentle" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "Direct" }));
    expect(within(group).getByRole("button", { name: "Direct" })).toHaveAttribute("aria-pressed", "true");
    expect(styles).toEqual([{ style: "direct" }]);
  });

  it("CO-2: Done saves the story's name, ends the session and opens the workbench", async () => {
    const user = userEvent.setup();
    renderAt("/coach/new");
    await screen.findByRole("heading", { level: 1, name: "Build a story" });
    await user.type(screen.getByRole("textbox", { name: "Your reply" }), "We were losing checkouts every week.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText(/Why did it matter/);
    await user.type(screen.getByRole("textbox", { name: "Story name" }), "Pushback from platform");
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Pushback from platform" })).toBeInTheDocument();
    const saved = mockStoryLibrary().find((s) => s.title === "Pushback from platform");
    expect(saved?.context).toBe("We were losing checkouts every week.");
    expect(screen.getByTestId("where")).toHaveTextContent(`/stories/${saved?.id}`);
  });

  it("CO-2: a session on an existing story names it and fills in around its parts", async () => {
    renderAt("/coach/new?story=s1");
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Story name" })).toHaveValue("Checkout migration");
    expect(parts()).toMatchObject({ context: "done", stakes: "now", action: "done", result: "next" });
  });

  it("CO-2: Done on a new story with nothing in it drops the story and returns to the library", async () => {
    const user = userEvent.setup();
    renderAt("/coach/new");
    await screen.findByRole("heading", { level: 1, name: "Build a story" });
    expect(mockStoryLibrary()).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByText("Stories")).toBeInTheDocument();
    expect(mockStoryLibrary()).toHaveLength(2);
  });

  it("CO-6: without the coach voice room the mic button is off and says why", async () => {
    renderAt("/coach/new");
    const mic = await screen.findByRole("button", { name: "Talk to the coach" });
    expect(mic).toBeDisabled();
    expect(mic).toHaveAccessibleDescription("Talking to the coach by voice is coming soon. Type for now.");
  });

  it("CO-6: with the voice room, the mic starts the coach by voice", async () => {
    const user = userEvent.setup();
    renderAt("/coach/new", { voiceReady: true });
    await user.click(await screen.findByRole("button", { name: "Talk to the coach" }));
    expect(await screen.findByText(/Tell me about one time you led a hard change/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop talking to the coach" })).toBeEnabled();
  });

  it("CO-2: a session that ended says so and takes no more turns", async () => {
    scriptMockCoach([{ message: "I'm going to end the session here.", parts: {}, ended: true }]);
    const user = userEvent.setup();
    renderAt("/coach/new");
    await screen.findByRole("heading", { level: 1, name: "Build a story" });
    await user.type(screen.getByRole("textbox", { name: "Your reply" }), "Something off topic.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/This session has ended/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Your reply" })).toBeNull();
  });
});

describe("workbench takes and versions", () => {
  it("CO-2: Work on it with the coach opens a coach session on the story", async () => {
    renderAt("/stories/s1");
    const takes = await screen.findByTestId("story-takes");
    expect(within(takes).getByRole("link", { name: "Work on it with the coach" })).toHaveAttribute(
      "href",
      "/coach/new?story=s1",
    );
  });

  it("CO-7: takes list newest first with date, channel and per-skill scores, and the practice notice", async () => {
    mockTakes([
      {
        id: "t1",
        story_id: "s1",
        channel: "text",
        text: "First telling.",
        duration_s: null,
        status: "scored",
        scores: [{ competency: "ownership", score: 2, justification: "j", quotes: [] }],
        reason: null,
        created_at: "2026-10-20T10:00:00Z",
      },
      {
        id: "t2",
        story_id: "s1",
        channel: "voice",
        text: "Second telling.",
        duration_s: 112,
        status: "scored",
        scores: [
          { competency: "ownership", score: 3, justification: "j", quotes: [] },
          { competency: "impact", score: 4, justification: "j", quotes: [] },
        ],
        reason: null,
        created_at: "2026-10-22T10:00:00Z",
      },
    ]);
    renderAt("/stories/s1");
    const list = await screen.findByRole("list", { name: "Takes, newest first" });
    const takes = within(list).getAllByTestId("story-take");
    expect(takes).toHaveLength(2);
    expect(takes[0]).toHaveTextContent("Take 2");
    expect(takes[0]).toHaveTextContent("Spoken · 1:52");
    expect(within(takes[0]).getByRole("list", { name: "Take 2 scores" })).toHaveTextContent("Ownership3 of 4");
    expect(within(takes[0]).getByRole("list", { name: "Take 2 scores" })).toHaveTextContent("Impact4 of 4");
    expect(takes[1]).toHaveTextContent("Take 1");
    expect(takes[1]).toHaveTextContent("Typed");
    expect(screen.getByTestId("practice-notice")).toHaveTextContent("not a prediction of any hiring decision");
    expect(screen.getByRole("button", { name: "Record take 3" })).toBeInTheDocument();
  });

  it("CO-7: Record a take stores a typed take and shows its scores once scored", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/takes")) sent.push(await request.clone().json());
    });
    renderAt("/stories/s1");
    await user.click(await screen.findByRole("button", { name: "Record a take" }));
    await user.type(screen.getByRole("textbox", { name: /Tell the story/ }), "I wrote the migration plan.");
    await user.click(screen.getByRole("button", { name: "Score this take" }));

    expect(sent).toEqual([{ text: "I wrote the migration plan.", channel: "text" }]);
    const take = await screen.findByTestId("story-take");
    expect(take).toHaveTextContent("Take 1");
    expect(await within(take).findByRole("list", { name: "Take 1 scores" })).toHaveTextContent("Ownership3 of 4");
    expect(screen.getByTestId("practice-notice")).toBeInTheDocument();
  });

  it("CO-7: a story with no skill tags asks for one before takes", async () => {
    renderAt("/stories/s2");
    const takes = await screen.findByTestId("story-takes");
    expect(within(takes).getByText(/Tag the story with at least one skill/)).toBeInTheDocument();
    expect(within(takes).queryByRole("button", { name: "Record a take" })).toBeNull();
  });

  it("CO-8: the coach writes a 60-second and a full version, with a toggle between them", async () => {
    const user = userEvent.setup();
    renderAt("/stories/s1");
    const versions = await screen.findByTestId("story-versions");
    await user.click(within(versions).getByRole("button", { name: "Write the versions" }));

    const length = await within(versions).findByRole("group", { name: "Story length" });
    expect(within(length).getByRole("button", { name: "60-second version" })).toHaveAttribute("aria-pressed", "true");
    const text = within(versions).getByTestId("story-version-text");
    expect(text).toHaveTextContent("Payments service nobody owned. I wrote the migration plan.");

    await user.click(within(length).getByRole("button", { name: "Full version" }));
    expect(within(length).getByRole("button", { name: "Full version" })).toHaveAttribute("aria-pressed", "true");
    expect(within(versions).getByTestId("story-version-text").textContent).toBe(
      "Payments service nobody owned.\n\nI wrote the migration plan.",
    );
    expect(within(versions).getByRole("button", { name: "Write them again" })).toBeInTheDocument();
  });

  it("CO-8: with no parts and no takes there is nothing to write from", async () => {
    resetMockStories([mockStory({ id: "s3", title: "Empty", skills: ["impact"] })]);
    renderAt("/stories/s3");
    const versions = await screen.findByTestId("story-versions");
    expect(within(versions).getByRole("button", { name: "Write the versions" })).toBeDisabled();
    expect(versions).toHaveTextContent("Fill in a part or record a take");
  });
});
