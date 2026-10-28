/**
 * ST-3: the story library and workbench with MSW (mocks/storyHandlers.ts, the shapes of
 * strong_api.stories). Also: the story pages send the user Home with `v2_enabled` off.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { server } from "../../mocks/node";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import type { StoryPatch } from "./api";
import { NewStoryPage } from "./NewStoryPage";
import { StoriesPage } from "./StoriesPage";
import { StoryWorkbenchPage } from "./StoryWorkbenchPage";
import { V2Only } from "./V2Only";

const PROVEN = mockStory({
  id: "s1",
  title: "Checkout migration",
  context: "Payments service nobody owned.",
  action: "I wrote the plan.",
  result: "Errors dropped 40 percent.",
  skills: ["ownership", "impact"],
  status: "proven",
  notes: [
    { text: "Older note", at: "2026-10-01T09:00:00Z", session_id: null, question_ref: null },
    { text: "Newer note", at: "2026-10-05T09:00:00Z", session_id: "5e551011-0000-4000-8000-000000000000", question_ref: "q1" },
  ],
  created_at: "2026-10-02T10:00:00Z",
});

const DRAFT = mockStory({
  id: "s2",
  title: "Pushback from platform",
  skills: ["conflict_handling"],
  created_at: "2026-10-03T10:00:00Z",
});

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories([PROVEN, DRAFT]);
});
afterEach(() => setFeatureOverrides({}));

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<p>Home</p>} />
          <Route path="/stories" element={<V2Only><StoriesPage /></V2Only>} />
          <Route path="/stories/new" element={<V2Only><NewStoryPage /></V2Only>} />
          <Route path="/stories/:storyId" element={<V2Only><StoryWorkbenchPage /></V2Only>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("story library", () => {
  const library = () => screen.getByRole("navigation", { name: "Story library" });

  it("ST-3: lists the stories, newest first, with status and skill tags", async () => {
    renderAt("/stories");
    const rows = await screen.findAllByTestId("story-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: /Pushback from platform/ })).toHaveAttribute("href", "/stories/s2");
    expect(rows[0]).toHaveTextContent("Draft · 0 of 5 parts · Conflict handling");
    expect(rows[1]).toHaveTextContent("Proven · Ownership, Impact");
  });

  it("ST-3: the studio opens the first story beside the list, in a read view", async () => {
    renderAt("/stories");
    expect(await screen.findByRole("heading", { level: 2, name: "Pushback from platform" })).toBeInTheDocument();
    const rows = screen.getAllByTestId("story-row");
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("aria-current", "page");
  });

  it("ST-3: filters by status (All, Proven, Needs work), by skill, in the URL, and searches by title", async () => {
    const user = userEvent.setup();
    renderAt("/stories");
    await screen.findAllByTestId("story-row");

    await user.click(within(library()).getByRole("button", { name: "Proven" }));
    expect(await screen.findByTestId("where")).toHaveTextContent("/stories?status=proven");
    await expect.poll(() => screen.getAllByTestId("story-row").map((r) => r.textContent)).toHaveLength(1);
    expect(screen.getByTestId("story-row")).toHaveTextContent("Checkout migration");

    await user.click(within(library()).getByRole("button", { name: "Needs work" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/stories?status=draft");

    await user.click(within(library()).getByRole("button", { name: "All 2" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Skill" }), "conflict_handling");
    expect(screen.getByTestId("where")).toHaveTextContent("/stories?skill=conflict_handling");
    await expect.poll(() => within(library()).queryByText("Checkout migration")).toBeNull();
    expect(screen.getByTestId("story-row")).toHaveTextContent("Pushback from platform");

    await user.selectOptions(screen.getByRole("combobox", { name: "Skill" }), "");
    await expect.poll(() => screen.getAllByTestId("story-row")).toHaveLength(2);
    await user.type(screen.getByRole("searchbox", { name: "Search stories" }), "checkout");
    expect(screen.getAllByTestId("story-row").map((r) => r.textContent)).toEqual([expect.stringContaining("Checkout migration")]);

    await user.clear(screen.getByRole("searchbox", { name: "Search stories" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Skill" }), "judgment");
    expect(await screen.findByText("No stories match these filters.")).toBeInTheDocument();
  });

  it("ST-3: the skill filter lists each skill once", async () => {
    renderAt("/stories");
    const options = within(await screen.findByRole("combobox", { name: "Skill" }))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toContain("Motivation");
    expect(new Set(options).size).toBe(options.length);
  });

  it("ST-3: an empty library says how to add a story", async () => {
    resetMockStories([]);
    renderAt("/stories");
    expect(await screen.findByText(/No stories yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New story with the coach" })).toHaveAttribute("href", "/coach/new");
    expect(screen.getByRole("link", { name: "Write one yourself" })).toHaveAttribute("href", "/stories/new");
  });
});

describe("story view", () => {
  it("ST-3: reads each part with its name, the status and the numbered fix notes, newest first", async () => {
    renderAt("/stories/s1");
    expect(await screen.findByRole("heading", { level: 2, name: "Checkout migration" })).toBeInTheDocument();
    const view = screen.getByRole("article");
    expect(within(view).getByText("Proven")).toBeInTheDocument();
    expect(view).toHaveTextContent("Proves Ownership and Impact");
    for (const label of ["Context", "Stakes", "Your action", "Result", "Reflection"]) {
      expect(within(view).getByText(label)).toBeInTheDocument();
    }
    expect(within(view).getByText("Payments service nobody owned.")).toBeInTheDocument();
    // An empty part offers the coach.
    expect(within(view).getAllByRole("link", { name: "Add it with the coach" })[0]).toHaveAttribute("href", "/coach/new?story=s1");
    expect(screen.queryByRole("textbox", { name: "Context" })).toBeNull();

    const notes = screen.getAllByTestId("story-note");
    expect(notes.map((n) => n.querySelector("p")?.textContent)).toEqual(["Newer note", "Older note"]);
    expect(notes[0]).toHaveTextContent(/^1/);
    expect(within(notes[0]).getByRole("link", { name: "Open the debrief" })).toHaveAttribute(
      "href",
      "/sessions/5e551011-0000-4000-8000-000000000000/debrief",
    );
  });

  it("ST-3: Edit story opens the form with each part, and the skills the story uses", async () => {
    const user = userEvent.setup();
    renderAt("/stories/s1");
    await user.click(await screen.findByRole("button", { name: "Edit story" }));
    for (const label of ["Context", "Stakes", "Your action", "Result", "Reflection"]) {
      expect(screen.getByRole("textbox", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("textbox", { name: "Context" })).toHaveValue("Payments service nobody owned.");
    expect(screen.getByRole("textbox", { name: "Stakes" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Ownership" })).toHaveAttribute("aria-pressed", "true");
    // Only the groups the story uses show; the rest open on request, each skill once.
    expect(screen.queryByRole("button", { name: "Judgment" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Show all skills/ }));
    expect(screen.getByRole("button", { name: "Judgment" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getAllByRole("button", { name: "Motivation" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Back to the story" }));
    expect(screen.queryByRole("textbox", { name: "Context" })).toBeNull();
  });

  it("ST-3: edits a story part by part and saves only what changed", async () => {
    const sent: StoryPatch[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PATCH") sent.push((await request.clone().json()) as StoryPatch);
    });
    const user = userEvent.setup();
    renderAt("/stories/s1");
    await user.click(await screen.findByRole("button", { name: "Edit story" }));
    const stakes = screen.getByRole("textbox", { name: "Stakes" });
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();

    await user.type(stakes, "2 percent of checkouts failed.");
    await user.clear(screen.getByRole("textbox", { name: "Result" }));
    await user.click(screen.getByRole("button", { name: /Show all skills/ }));
    await user.click(screen.getByRole("button", { name: "Judgment" }));
    await user.click(save);

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(sent).toEqual([
      { stakes: "2 percent of checkouts failed.", result: null, skills: ["ownership", "impact", "judgment"] },
    ]);
    expect(save).toBeDisabled();
    server.events.removeAllListeners();
  });

  it("ST-3: a story needs a title", async () => {
    const user = userEvent.setup();
    renderAt("/stories/s1");
    await user.click(await screen.findByRole("button", { name: "Edit story" }));
    await user.clear(screen.getByRole("textbox", { name: "Title" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A story needs a title.");
  });

  it("ST-3: shows the API's error when a story is not found", async () => {
    server.use(http.get("*/api/stories/:id", () => HttpResponse.json({ detail: "Story not found" }, { status: 404 })));
    renderAt("/stories/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Story not found");
  });
});

describe("new story", () => {
  it("ST-3: New story creates a manual draft and opens it in the studio", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new?skill=conflict_handling");
    expect(screen.getByRole("button", { name: "Conflict handling" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Create story" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the story a title.");

    await user.type(screen.getByRole("textbox", { name: "Title" }), "Hiring my first PM");
    await user.click(screen.getByRole("button", { name: "Create story" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Hiring my first PM" })).toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toMatch(/^\/stories\/[0-9a-f-]{36}$/);
    const view = screen.getByRole("article");
    expect(within(view).getByText("Draft")).toBeInTheDocument();
    expect(view).toHaveTextContent("Proves Conflict handling");
  });
});

describe("v2 flag", () => {
  it("ST-3: with v2_enabled off, the story pages send the user Home", async () => {
    setFeatureOverrides({ v2_enabled: false });
    renderAt("/stories");
    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });
});
