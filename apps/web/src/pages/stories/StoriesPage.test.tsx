/**
 * Career Stories with Strova (U10) with MSW (mocks/storyHandlers.ts and suggestionHandlers.ts,
 * the shapes of strong_api.stories and strong_api.suggestions): the list and part-by-part editing
 * (ST-3), the status to show (ST-8), the page (ST-9), Write it yourself (ST-10), Review with
 * Strova (ST-11), Ask Strova (ST-13) and the story page (ST-14). The story pages send the user
 * Home with `v2_enabled` off.
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
import { ReviewPage } from "./ReviewPage";
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

const READY = mockStory({
  id: "s3",
  title: "Payments outage",
  context: "A deploy broke card payments.",
  stakes: "Every minute cost merchants sales.",
  action: "I rolled back and led the incident call.",
  result: "Payments recovered within the hour.",
  reflection: "We added a canary step.",
  skills: ["ownership"],
  created_at: "2026-10-01T10:00:00Z",
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
          <Route path="/stories/:storyId/review" element={<V2Only><ReviewPage /></V2Only>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Career Stories (ST-9)", () => {
  it("ST-9: the page has, in order: start a new story, resume ideas, Ask Strova, your stories, Strova suggests", async () => {
    renderAt("/stories");
    expect(await screen.findByRole("heading", { level: 1, name: "Career Stories with Strova" })).toBeInTheDocument();
    const order = [
      screen.getByRole("heading", { name: "Start a new story" }),
      screen.getByRole("form", { name: "Ask Strova" }),
      screen.getByRole("heading", { name: "Your stories" }),
      screen.getByTestId("strova-suggests"),
    ];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: /Craft with Strova/ })).toHaveAttribute("href", "/coach/new");
    expect(screen.getByRole("link", { name: /Write it yourself/ })).toHaveAttribute("href", "/stories/new");
    // Strova suggests starts collapsed.
    expect(screen.getByTestId("strova-suggests")).not.toHaveAttribute("open");
  });

  it("ST-3, ST-8: your stories list newest first with Draft, Ready or Proven, the skills and the coverage", async () => {
    resetMockStories([PROVEN, DRAFT, READY]);
    renderAt("/stories");
    const rows = await screen.findAllByTestId("story-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Pushback from platform"),
      expect.stringContaining("Checkout migration"),
      expect.stringContaining("Payments outage"),
    ]);
    expect(rows[0]).toHaveTextContent("Conflict handling · 0 of 5 parts · you wrote itDraft");
    expect(rows[1]).toHaveTextContent("Proven");
    expect(rows[2]).toHaveTextContent("Ready");
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/stories/s2");
    expect(screen.getByText("1 Proven · 1 Ready · 1 Draft")).toBeInTheDocument();
    const coverage = screen.getByRole("list", { name: "Skill coverage" });
    expect(within(coverage).getByText("Ownership · covered")).toBeInTheDocument();
    expect(within(coverage).getByText("Conflict handling · thin")).toBeInTheDocument();
    expect(within(coverage).getByText("Communication · missing")).toBeInTheDocument();
  });

  it("ST-3: an empty library says what a story is, with the coach one click away", async () => {
    resetMockStories([]);
    renderAt("/stories");
    const empty = await screen.findByTestId("stories-empty");
    expect(empty).toHaveTextContent("A story is one moment from your career, told in 5 parts");
    expect(within(empty).getByRole("link", { name: "Build my first story" })).toHaveAttribute("href", "/coach/new");
  });

  it("ST-9: Strova suggests lists this user's suggestions for their stories, collapsed", async () => {
    renderAt("/stories");
    const box = await screen.findByTestId("strova-suggests");
    expect(await within(box).findByText("4 for your stories")).toBeInTheDocument();
    expect(within(box).getByRole("group", { name: "Tailor for Stripe" })).toBeInTheDocument();
    expect(within(box).getByRole("link", { name: "Craft it with Strova" })).toHaveAttribute(
      "href",
      "/coach/new?skill=conflict_handling",
    );
  });

  it("ST-13: Ask Strova answers from your stories, naming the story it leans on", async () => {
    const user = userEvent.setup();
    renderAt("/stories");
    await user.type(await screen.findByRole("textbox", { name: "Ask Strova" }), "Which story should I lead with?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("region", { name: "Strova's answer" });
    expect(answer).toHaveTextContent("Lead with “Checkout migration”. Say the result first: Errors dropped 40 percent.");
    expect(within(answer).getByRole("link", { name: "Checkout migration" })).toHaveAttribute("href", "/stories/s1");
  });
});

describe("Write it yourself (ST-10)", () => {
  it("ST-10: Save as a Draft saves the title and parts and goes back to Career Stories", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new?skill=conflict_handling");
    expect(screen.getByRole("textbox", { name: /Your action/ })).toHaveAttribute(
      "placeholder",
      "What you did yourself, and the trade-offs",
    );
    await user.click(screen.getByRole("button", { name: "Save as a Draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the story a title.");
    await user.type(screen.getByRole("textbox", { name: "Story title" }), "Hiring my first PM");
    await user.type(screen.getByRole("textbox", { name: /Context/ }), "We had no product manager.");
    await user.click(screen.getByRole("button", { name: "Save as a Draft" }));
    await expect.poll(() => screen.getByTestId("where").textContent).toBe("/stories");
    const rows = await screen.findAllByTestId("story-row");
    expect(rows[0]).toHaveTextContent("Hiring my first PM");
    expect(rows[0]).toHaveTextContent("Conflict handling · 1 of 5 parts");
  });

  it("ST-10, ST-11: Save and ask Strova to review opens Review with Strova on the new story", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new");
    await user.type(screen.getByRole("textbox", { name: "Story title" }), "Pushback on the API");
    await user.type(screen.getByRole("textbox", { name: /Your action/ }), "We talked to them and worked it out.");
    await user.click(screen.getByRole("button", { name: "Save and ask Strova to review" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Pushback on the API" })).toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toMatch(/^\/stories\/[0-9a-f-]{36}\/review$/);
    const review = screen.getByRole("region", { name: "Strova's review" });
    expect(await within(review).findByRole("heading", { name: "Strova's review" })).toBeInTheDocument();
  });
});

describe("Review with Strova (ST-11)", () => {
  it("ST-11: the review shows per-part notes; Accept applies an edit; a missing part offers Answer with Strova", async () => {
    const user = userEvent.setup();
    renderAt("/stories/s2/review");
    const panel = await screen.findByRole("region", { name: "Strova's review" });
    expect(within(panel).getByRole("heading", { name: "Ask Strova to review" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review with Strova" }));
    const edit = await within(panel).findByRole("group", { name: "Edit to Result" });
    expect(within(edit).getByText("We finished a week before Black Friday and not one payment failed.")).toBeInTheDocument();
    await user.click(within(edit).getByRole("button", { name: "Accept" }));
    expect(await within(panel).findByText("Result updated.")).toBeInTheDocument();
    await expect
      .poll(async () => within(screen.getByTestId("part-result")).queryByText(/not one payment failed/))
      .not.toBeNull();
    const missing = within(panel).getByTestId("note-reflection");
    expect(missing).toHaveTextContent("Reflection is missing.");
    expect(within(missing).getByRole("link", { name: "Answer with Strova" })).toHaveAttribute(
      "href",
      "/coach/new?story=s2",
    );
  });

  it("ST-11: Skip hides an edit without changing the story", async () => {
    const user = userEvent.setup();
    renderAt("/stories/s2/review");
    await user.click(await screen.findByRole("button", { name: "Review with Strova" }));
    const panel = screen.getByRole("region", { name: "Strova's review" });
    const edit = await within(panel).findByRole("group", { name: "Edit to Result" });
    await user.click(within(edit).getByRole("button", { name: "Skip" }));
    expect(within(panel).queryByRole("group", { name: "Edit to Result" })).toBeNull();
    expect(within(screen.getByTestId("part-result")).getByText("Not written yet")).toBeInTheDocument();
  });
});

describe("story page (ST-14)", () => {
  it("ST-14, ST-8: status steps, skills, the parts with their versions, used-for notes and the source", async () => {
    resetMockStories([
      { ...PROVEN, notes: [...PROVEN.notes, { text: "For Stripe: bring forward the 40 percent.", at: "2026-10-06T09:00:00Z", session_id: null, question_ref: null }] },
      DRAFT,
    ]);
    renderAt("/stories/s1");
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    expect(screen.getByTestId("story-status")).toHaveTextContent("Proven");
    const steps = screen.getByRole("list", { name: "Status steps" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Draft", "Ready", "Proven"]);
    expect(within(steps).getByText("Proven")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("· proves Ownership, Impact")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review with Strova" })).toHaveAttribute("href", "/stories/s1/review");
    const parts = screen.getByRole("region", { name: "Story parts" });
    for (const label of ["Story parts", "60-second version", "Full version"]) {
      expect(within(parts).getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(within(parts).getByText("Payments service nobody owned.")).toBeInTheDocument();
    const usedFor = screen.getByRole("region", { name: "Used for" });
    expect(usedFor).toHaveTextContent("For Stripe: bring forward the 40 percent.");
    expect(screen.getByTestId("story-source")).toHaveTextContent("Written by you");
  });

  it("ST-3: reads each part with its name and the numbered fix notes, newest first", async () => {
    renderAt("/stories/s1");
    const parts = await screen.findByRole("region", { name: "Story parts" });
    for (const label of ["Context", "Stakes", "Your action", "Result", "Reflection"]) {
      expect(within(parts).getByText(label)).toBeInTheDocument();
    }
    // An empty part offers the coach.
    expect(within(parts).getAllByRole("link", { name: "Add it with the coach" })[0]).toHaveAttribute(
      "href",
      "/coach/new?story=s1",
    );
    const notes = screen.getAllByTestId("story-note");
    expect(notes.map((n) => n.querySelector("p")?.textContent)).toEqual(["Newer note", "Older note"]);
    expect(within(notes[0]).getByRole("link", { name: "Open the debrief" })).toHaveAttribute(
      "href",
      "/sessions/5e551011-0000-4000-8000-000000000000/debrief",
    );
  });

  it("ST-14: the parts are stacked with a filled dot when written and an open dot when empty, under underline tabs", async () => {
    resetMockStories([DRAFT]);
    renderAt("/stories/s2");
    const tabs = await screen.findByRole("group", { name: "Story length" });
    expect(tabs).toHaveClass("segmented--tabs");
    expect(within(tabs).getByRole("button", { name: "Story parts" })).toHaveAttribute("aria-pressed", "true");
    const parts = screen.getByTestId("story-versions").querySelectorAll("li[data-part]");
    expect(parts).toHaveLength(5);
    for (const li of parts) {
      const written = Boolean(li.querySelector("p:not(.muted)"));
      expect(li.querySelector(".story-view__part-label")?.textContent?.startsWith(written ? "●" : "○")).toBe(true);
    }
  });

  it("ST-14: an open suggestion for the story can be applied, then undone", async () => {
    resetMockStories([{ ...PROVEN, id: "11111111-1111-4111-8111-111111111111" }]);
    const user = userEvent.setup();
    renderAt("/stories/11111111-1111-4111-8111-111111111111");
    const tune = await screen.findByRole("group", { name: "Tune this story" });
    expect(tune).toHaveTextContent("We finished a week before Black Friday and not one payment failed.");
    await user.click(within(tune).getByRole("button", { name: "Apply" }));
    const done = await screen.findByText("Applied to this story.");
    await user.click(within(done.closest("[role=status]") as HTMLElement).getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("group", { name: "Tune this story" })).toBeInTheDocument();
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

describe("v2 flag", () => {
  it("ST-3: with v2_enabled off, the story pages send the user Home", async () => {
    setFeatureOverrides({ v2_enabled: false });
    renderAt("/stories");
    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });
});
