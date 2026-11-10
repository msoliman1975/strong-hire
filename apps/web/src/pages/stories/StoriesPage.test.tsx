/**
 * Career Stories with Strova (U10) with MSW (mocks/storyHandlers.ts and suggestionHandlers.ts,
 * the shapes of strong_api.stories and strong_api.suggestions): the list and part-by-part editing
 * (ST-3), the status to show (ST-8), the page (ST-9), Write it yourself (ST-10), Review with
 * Strova (ST-11), Ask Strova (ST-13), the story page (ST-14) and the Career Stories redesign
 * (CS-5 to CS-17, docs/stories-redesign/spec.md). The story pages send the user
 * Home with `v2_enabled` off.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const IDEA = {
  kind: "resume_idea" as const,
  achievement: "Cut AWS spend 30% by rightsizing",
  role: "Senior Engineer, Fernhill",
  resume_id: "r2",
  resume_line_ref: "roles[0].achievements[1]",
  resumes: 2,
  skills: ["impact" as const],
  missing_parts: ["stakes" as const, "reflection" as const],
};
const GAP = {
  kind: "missing_skill" as const,
  suggestion_id: "5a000000-0000-4000-8000-0000000000aa",
  competency: "learning_from_failure" as const,
  job_target_id: "j1",
  company: "Stripe",
  job_title: "Backend Engineer",
  reason: "Stripe asks about a failure and no story shows one.",
};

function withRecommendations(ideas = [IDEA], skills = [GAP]) {
  server.use(http.get("*/api/stories/recommendations", () => HttpResponse.json({ ideas, skills })));
}

const TIPPED = mockStory({ ...PROVEN, id: "11111111-1111-4111-8111-111111111111" });

/** Open the row menu of one story and choose an item from it. */
async function pick(user: ReturnType<typeof userEvent.setup>, title: string, item: string) {
  const summary = await screen.findByLabelText(`More for ${title}`);
  await user.click(summary);
  await user.click(within(summary.closest("details") as HTMLElement).getByRole("menuitem", { name: item }));
}

describe("Career Stories (CS-5 to CS-17)", () => {
  it("CS-5, CS-8: stories come first, then the recommended rows; + New story crafts or writes", async () => {
    withRecommendations();
    renderAt("/stories");
    expect(await screen.findByRole("heading", { level: 1, name: "Career Stories with Strova" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+ New story" })).toHaveAttribute("href", "/coach/new");
    const more = screen.getByLabelText("More ways to start");
    expect(more.closest("details")).not.toHaveAttribute("open");
    const menu = more.closest("details") as HTMLElement;
    expect(within(menu).getByRole("menuitem", { name: /Write it yourself/ })).toHaveAttribute("href", "/stories/new");
    const list = await screen.findByRole("region", { name: "Stories" });
    await within(list).findAllByTestId("recommended-row");
    const items = within(list).getAllByRole("listitem").filter((li) => li.parentElement?.closest("li") === null);
    expect(items.map((li) => li.dataset.testid)).toEqual(["story-row", "story-row", "recommended-row", "recommended-row"]);
    // Job gaps come before resume ideas.
    const recs = within(list).getAllByTestId("recommended-row");
    expect(recs[0]).toHaveTextContent("Learning from failure story");
    expect(recs[0]).toHaveTextContent("For Stripe – Backend Engineer");
    expect(recs[1]).toHaveTextContent("Cut AWS spend 30% by rightsizing");
    expect(recs[1]).toHaveTextContent("From 2 resumes · Impact");
    // The old cards are gone.
    expect(screen.queryByTestId("strova-suggests")).toBeNull();
    expect(screen.queryByTestId("resume-ideas")).toBeNull();
  });

  it("ST-3, ST-8, CS-5: drafts first, then Ready and Proven, with the skills and the coverage", async () => {
    withRecommendations([], []);
    resetMockStories([PROVEN, DRAFT, READY]);
    renderAt("/stories");
    const rows = await screen.findAllByTestId("story-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Pushback from platform"),
      expect.stringContaining("Checkout migration"),
      expect.stringContaining("Payments outage"),
    ]);
    expect(rows[0]).toHaveTextContent("Conflict handling · 0 of 5 parts · you wrote it");
    expect(rows[0]).toHaveTextContent("Draft");
    expect(rows[1]).toHaveTextContent("Proven");
    expect(rows[2]).toHaveTextContent("Ready");
    expect(within(rows[0]).getByRole("link", { name: "Pushback from platform" })).toHaveAttribute("href", "/stories/s2");
    const coverage = screen.getByRole("group", { name: "Skill coverage" });
    expect(within(coverage).getByRole("button", { name: "Ownership: covered" })).toBeInTheDocument();
    expect(within(coverage).getByRole("button", { name: "Conflict handling: thin" })).toBeInTheDocument();
    expect(within(coverage).getByRole("button", { name: "Communication: missing" })).toBeInTheDocument();
  });

  it("ST-3: an empty library says what a story is, with the coach one click away", async () => {
    withRecommendations([], []);
    resetMockStories([]);
    renderAt("/stories");
    const empty = await screen.findByTestId("stories-empty");
    expect(empty).toHaveTextContent("A story is one moment from your career, told in 5 parts");
    expect(within(empty).getByRole("link", { name: "Build my first story" })).toHaveAttribute("href", "/coach/new");
  });

  it("CS-5: with no stories yet, the recommendations show with a hint", async () => {
    withRecommendations([IDEA], []);
    resetMockStories([]);
    renderAt("/stories");
    expect(await screen.findByText("Strova found these in your resume. Start with one.")).toBeInTheDocument();
    expect(screen.getAllByTestId("recommended-row")).toHaveLength(1);
  });

  it("CS-6: the filter chips count and filter the list, and the choice is in the URL", async () => {
    withRecommendations();
    const user = userEvent.setup();
    resetMockStories([PROVEN, DRAFT, mockStory({ ...READY, archived_at: "2026-10-30T10:00:00Z" })]);
    renderAt("/stories");
    await screen.findAllByTestId("recommended-row");
    const show = screen.getByRole("group", { name: "Show" });
    expect(within(show).getByRole("button", { name: "All 4" })).toHaveAttribute("aria-pressed", "true");
    expect(within(show).getByRole("button", { name: "Archived 1" })).toBeInTheDocument();
    await user.click(within(show).getByRole("button", { name: "Recommended 2" }));
    expect(screen.queryAllByTestId("story-row")).toHaveLength(0);
    expect(screen.getAllByTestId("recommended-row")).toHaveLength(2);
    expect(screen.getByTestId("where").textContent).toBe("/stories?show=recommended");
    await user.click(within(show).getByRole("button", { name: "Archived 1" }));
    expect(screen.getAllByTestId("story-row").map((r) => r.textContent)).toEqual([
      expect.stringContaining("Payments outage"),
    ]);
    await user.click(within(show).getByRole("button", { name: "Drafts 1" }));
    expect(screen.getAllByTestId("story-row")).toHaveLength(1);
    expect(screen.queryAllByTestId("recommended-row")).toHaveLength(0);
  });

  it("CS-7: a coverage chip filters stories and recommendations to that skill; again clears it", async () => {
    withRecommendations();
    const user = userEvent.setup();
    renderAt("/stories");
    await screen.findAllByTestId("recommended-row");
    const chip = screen.getByRole("button", { name: "Impact: covered" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByTestId("story-row").map((r) => r.textContent)).toEqual([
      expect.stringContaining("Checkout migration"),
    ]);
    expect(screen.getAllByTestId("recommended-row").map((r) => r.textContent)).toEqual([
      expect.stringContaining("Cut AWS spend"),
    ]);
    await user.click(chip);
    expect(screen.getAllByTestId("story-row")).toHaveLength(2);
  });

  it("CS-9, CS-11: Start crafts or writes from the recommendation, prefilled", async () => {
    withRecommendations();
    renderAt("/stories");
    const [gap, idea] = await screen.findAllByTestId("recommended-row");
    expect(within(idea).getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/coach/new?resume=r2&idea=roles%5B0%5D.achievements%5B1%5D",
    );
    expect(within(idea).getByRole("menuitem", { name: /Write it yourself/ })).toHaveAttribute(
      "href",
      "/stories/new?skill=impact&idea=Cut+AWS+spend+30%25+by+rightsizing",
    );
    expect(within(gap).getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/coach/new?skill=learning_from_failure&job=j1",
    );
  });

  it("CS-3, CS-9: dismissing a resume idea sends it for that resume line", async () => {
    let dismissed: unknown = null;
    withRecommendations([IDEA], []);
    server.use(
      http.post("*/api/resumes/:id/story-ideas/dismiss", async ({ params, request }) => {
        dismissed = { id: params.id, body: await request.json() };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderAt("/stories");
    await user.click(await screen.findByRole("button", { name: `Dismiss: ${IDEA.achievement}` }));
    await expect.poll(() => dismissed).toEqual({ id: "r2", body: { resume_line_ref: "roles[0].achievements[1]" } });
  });

  it("CS-10: a story's job tips show as a tag and open under the row", async () => {
    withRecommendations([], []);
    resetMockStories([TIPPED, DRAFT]);
    const user = userEvent.setup();
    renderAt("/stories");
    const tag = await screen.findByRole("button", { name: "Tips: Stripe 1" });
    await user.click(tag);
    const tips = screen.getByRole("region", { name: "Tips for Checkout migration" });
    expect(within(tips).getByRole("group", { name: "For Stripe" })).toHaveTextContent("Lead with the rollback plan");
    expect(within(tips).getByRole("button", { name: "Add to notes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tune 1" })).toBeInTheDocument();
  });

  it("CS-12: Rename in the row menu edits the title in place; Escape cancels, Enter saves", async () => {
    withRecommendations([], []);
    const user = userEvent.setup();
    renderAt("/stories");
    await pick(user, "Checkout migration", "Rename");
    const field = screen.getByRole("textbox", { name: "Story name" });
    expect(field).toHaveValue("Checkout migration");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Story name" })).toBeNull();
    await pick(user, "Checkout migration", "Rename");
    await user.clear(screen.getByRole("textbox", { name: "Story name" }));
    await user.type(screen.getByRole("textbox", { name: "Story name" }), "Checkout cutover{Enter}");
    expect(await screen.findByRole("link", { name: "Checkout cutover" })).toHaveAttribute("href", "/stories/s1");
  });

  it("CS-13, CS-14: Archive moves a story to Archived, out of the coverage; Unarchive brings it back", async () => {
    withRecommendations([], []);
    const user = userEvent.setup();
    renderAt("/stories");
    await pick(user, "Checkout migration", "Archive");
    await expect.poll(() => screen.getAllByTestId("story-row").length).toBe(1);
    expect(screen.getByRole("button", { name: "Ownership: missing" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archived 1" }));
    const row = screen.getByTestId("story-row");
    expect(row).toHaveTextContent("Checkout migration");
    expect(row).toHaveTextContent("Archived");
    await pick(user, "Checkout migration", "Unarchive");
    await expect.poll(() => screen.queryAllByTestId("story-row").length).toBe(0);
    await user.click(screen.getByRole("button", { name: "All 2" }));
    expect(screen.getAllByTestId("story-row")).toHaveLength(2);
  });

  it("CS-15, CS-17: Delete asks first, then hides the story with Undo; Restore is under Archived", async () => {
    withRecommendations([], []);
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    renderAt("/stories");
    await pick(user, "Pushback from platform", "Delete");
    expect(confirm).toHaveBeenCalledWith('Delete "Pushback from platform"? You can undo this for 30 days.');
    expect(screen.getAllByTestId("story-row")).toHaveLength(2); // cancelled
    await pick(user, "Pushback from platform", "Delete");
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent('Deleted "Pushback from platform".');
    await expect.poll(() => screen.getAllByTestId("story-row").length).toBe(1);
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await expect.poll(() => screen.getAllByTestId("story-row").length).toBe(2);
    // Delete again, then restore from Archived.
    await pick(user, "Pushback from platform", "Delete");
    await expect.poll(() => screen.getAllByTestId("story-row").length).toBe(1);
    await user.click(screen.getByRole("button", { name: "Archived 0" }));
    const deleted = screen.getByTestId("recently-deleted");
    await user.click(within(deleted).getByText(/Recently deleted \(1\)/));
    await user.click(within(deleted).getByRole("button", { name: "Restore" }));
    await user.click(await screen.findByRole("button", { name: "All 2" }));
    expect(screen.getAllByTestId("story-row")).toHaveLength(2);
    confirm.mockRestore();
  });

  it("ST-13, D-5: Ask Strova opens in a side panel and answers from your stories", async () => {
    withRecommendations([], []);
    const user = userEvent.setup();
    renderAt("/stories");
    await user.click(await screen.findByRole("button", { name: "Ask Strova" }));
    const panel = screen.getByRole("complementary", { name: "Ask Strova panel" });
    await user.type(within(panel).getByRole("textbox", { name: "Ask Strova" }), "Which story should I lead with?");
    await user.click(within(panel).getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("region", { name: "Strova's answer" });
    expect(answer).toHaveTextContent("Lead with “Checkout migration”. Say the result first: Errors dropped 40 percent.");
    expect(within(answer).getByRole("link", { name: "Checkout migration" })).toHaveAttribute("href", "/stories/s1");
    await user.click(screen.getByRole("button", { name: "Close Ask Strova" }));
    expect(screen.queryByRole("complementary", { name: "Ask Strova panel" })).toBeNull();
  });
});

describe("Write it yourself (ST-10)", () => {
  it("D-7, CS-9: from a recommended resume idea, the title, result and skills are prefilled", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new?skill=impact&skill=ownership&idea=Cut+AWS+spend+30%25+by+rightsizing");
    expect(screen.getByTestId("from-idea")).toHaveTextContent("From your resume: Cut AWS spend 30% by rightsizing.");
    expect(screen.getByRole("textbox", { name: "Story title" })).toHaveValue("Cut AWS spend 30% by rightsizing");
    await user.click(screen.getByRole("radio", { name: /Five free-text parts/ }));
    expect(screen.getByRole("textbox", { name: /Result/ })).toHaveValue("Cut AWS spend 30% by rightsizing");
    await user.click(screen.getByRole("button", { name: "Save as a Draft" }));
    await expect.poll(() => screen.getByTestId("where").textContent).toBe("/stories");
    const row = (await screen.findAllByTestId("story-row")).find((r) => r.textContent?.includes("Cut AWS spend"));
    expect(row).toHaveTextContent("Impact, Ownership · 1 of 5 parts");
  });

  it("ST-10: Save as a Draft saves the title and parts and goes back to Career Stories", async () => {
    const user = userEvent.setup();
    renderAt("/stories/new?skill=conflict_handling");
    await user.click(screen.getByRole("radio", { name: /Five free-text parts/ })); // the classic form
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
    await user.click(screen.getByRole("radio", { name: /Five free-text parts/ })); // the classic form
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
  it("ST-14: Rename names the story in place; Escape cancels, Enter saves", async () => {
    resetMockStories([PROVEN, DRAFT]);
    const user = userEvent.setup();
    renderAt("/stories/s1");
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const field = screen.getByRole("textbox", { name: "Story name" });
    expect(field).toHaveValue("Checkout migration");
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.clear(screen.getByRole("textbox", { name: "Story name" }));
    await user.type(screen.getByRole("textbox", { name: "Story name" }), "Black Friday checkout move{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "Black Friday checkout move" })).toBeInTheDocument();
  });

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
