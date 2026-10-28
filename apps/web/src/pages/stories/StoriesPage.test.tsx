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
  it("ST-3: lists the stories, newest first, with status and skill tags", async () => {
    renderAt("/stories");
    const rows = await screen.findAllByTestId("story-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Pushback from platform" })).toHaveAttribute("href", "/stories/s2");
    expect(rows[0]).toHaveTextContent("Draft");
    expect(rows[0]).toHaveTextContent("Conflict handling");
    expect(rows[1]).toHaveTextContent("Proven");
    expect(within(rows[1]).getByRole("list", { name: "Skills" })).toHaveTextContent("OwnershipImpact");
    // Parts done are said in text, not only in color.
    expect(rows[1]).toHaveTextContent("3 of 5 parts written: context, action, result.");
  });

  it("ST-3: filters by status and by skill, in the URL", async () => {
    const user = userEvent.setup();
    renderAt("/stories");
    await screen.findAllByTestId("story-row");

    await user.click(screen.getByRole("button", { name: "Proven" }));
    expect(await screen.findByTestId("where")).toHaveTextContent("/stories?status=proven");
    await expect.poll(() => screen.getAllByTestId("story-row").map((r) => r.textContent)).toHaveLength(1);
    expect(screen.getByTestId("story-row")).toHaveTextContent("Checkout migration");

    await user.click(screen.getByRole("button", { name: "All" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Skill" }), "conflict_handling");
    expect(screen.getByTestId("where")).toHaveTextContent("/stories?skill=conflict_handling");
    await expect.poll(() => screen.queryByText("Checkout migration")).toBeNull();
    expect(screen.getByTestId("story-row")).toHaveTextContent("Pushback from platform");

    await user.selectOptions(screen.getByRole("combobox", { name: "Skill" }), "judgment");
    expect(await screen.findByText("No stories match these filters.")).toBeInTheDocument();
  });

  it("ST-3: an empty library says how to add a story", async () => {
    resetMockStories([]);
    renderAt("/stories");
    expect(await screen.findByText(/No stories yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New story" })).toHaveAttribute("href", "/stories/new");
  });
});

describe("story workbench", () => {
  it("ST-3: shows each part with its name, the status and the fix notes newest first", async () => {
    renderAt("/stories/s1");
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    expect(screen.getByText("Proven")).toBeInTheDocument();
    for (const label of ["Context", "Stakes", "Your action", "Result", "Reflection"]) {
      expect(screen.getByRole("textbox", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("textbox", { name: "Context" })).toHaveValue("Payments service nobody owned.");
    expect(screen.getByRole("textbox", { name: "Stakes" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Ownership" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Judgment" })).toHaveAttribute("aria-pressed", "false");

    const notes = screen.getAllByTestId("story-note");
    expect(notes.map((n) => n.querySelector("p")?.textContent)).toEqual(["Newer note", "Older note"]);
    expect(within(notes[0]).getByRole("link", { name: "Open the debrief" })).toHaveAttribute(
      "href",
      "/sessions/5e551011-0000-4000-8000-000000000000/debrief",
    );
    expect(screen.getByTestId("story-takes")).toHaveTextContent("Takes and versions");
  });

  it("ST-3: edits a story part by part and saves only what changed", async () => {
    const sent: StoryPatch[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PATCH") sent.push((await request.clone().json()) as StoryPatch);
    });
    const user = userEvent.setup();
    renderAt("/stories/s1");
    const stakes = await screen.findByRole("textbox", { name: "Stakes" });
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();

    await user.type(stakes, "2 percent of checkouts failed.");
    await user.clear(screen.getByRole("textbox", { name: "Result" }));
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
    const title = await screen.findByRole("textbox", { name: "Title" });
    await user.clear(title);
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
  it("ST-3: New story creates a manual draft and opens it in the workbench", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new?skill=conflict_handling");
    expect(screen.getByRole("button", { name: "Conflict handling" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Create story" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the story a title.");

    await user.type(screen.getByRole("textbox", { name: "Title" }), "Hiring my first PM");
    await user.click(screen.getByRole("button", { name: "Create story" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Hiring my first PM" })).toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toMatch(/^\/stories\/[0-9a-f-]{36}$/);
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Conflict handling" })).toHaveAttribute("aria-pressed", "true");
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
