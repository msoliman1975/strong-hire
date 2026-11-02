/**
 * SC-10, SC-11 (UI), SC-12 (UI), SC-13 (UI): the organized story page, with MSW
 * (mocks/outlineMock.ts, the shapes of strong_api.stories.outline_api).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { server } from "../../mocks/node";
import { mockOutline } from "../../mocks/outlineMock";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { renderLegacy } from "../../mocks/craftMock";
import { setFeatureOverrides } from "../../theme/features";
import { ReviewPage } from "./ReviewPage";
import { StoryPage } from "./StoryPage";
import { V2Only } from "./V2Only";

const styled = (id: string, style: "star" | "carl" = "star") => {
  const outline = mockOutline(style);
  return mockStory({ id, title: "Checkout migration", style, outline, ...renderLegacy(outline) });
};
const CLASSIC = mockStory({
  id: "c1",
  title: "Pushback from platform",
  context: "The platform team refused to change an API.",
  stakes: "We would miss the holiday launch.",
  action: "I mapped what each team needed.",
});

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories([styled("s1"), styled("s2", "carl"), CLASSIC]);
});
afterEach(() => setFeatureOverrides({}));

function renderStory(id: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/stories/${id}`]}>
        <Routes>
          <Route path="/stories/:storyId" element={<V2Only><StoryPage /></V2Only>} />
          <Route path="/coach/new" element={<p>Coach</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const section = (name: string) => screen.getAllByTestId("outline-section").find((s) => s.dataset.section === name)!;
const slot = (id: string) => screen.getAllByTestId("outline-slot").find((s) => s.dataset.slot === id)!;

function requests(method: string, suffix: string): unknown[] {
  const seen: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.method === method && new URL(request.url).pathname.endsWith(suffix)) {
      const text = await request.clone().text();
      seen.push(text ? JSON.parse(text) : null);
    }
  });
  return seen;
}

describe("SC-10: the outline, edited in place", () => {
  it("SC-10: sections in style order, numbered steps, the metric as before → after, required empty slots marked", async () => {
    renderStory("s1");
    await screen.findByTestId("outline-story");
    expect(screen.getAllByTestId("outline-section").map((s) => s.dataset.section)).toEqual([
      "situation",
      "task",
      "action",
      "result",
      "learning",
    ]);
    expect(screen.getByTestId("story-style")).toHaveTextContent("STAR");
    expect(within(section("action")).getByText("Step 1")).toBeInTheDocument();
    expect(screen.getByTestId("metric-line")).toHaveTextContent("2% → 0.3%");
    expect(slot("slot-learning-lesson-x")).toHaveTextContent("Empty · needed for Ready");
    expect(slot("slot-situation-org-x")).toHaveTextContent("Skipped");
    expect(slot("slot-situation-role-x")).toHaveTextContent("From your words");
    expect(within(section("task")).getByText(/Also, if you have them/)).toBeInTheDocument();
    expect(screen.getByTestId("story-status")).toHaveTextContent("Draft");
  });

  it("SC-10, SC-3: a slot is edited in place, Save or Cancel, and the status steps follow", async () => {
    const patches = requests("PATCH", "/outline");
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(within(slot("slot-learning-lesson-x")).getByRole("button", { name: "Add The lesson" }));
    await user.type(screen.getByLabelText("The lesson"), "Ship in small steps.");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(patches).toEqual([]);
    await user.click(within(slot("slot-learning-lesson-x")).getByRole("button", { name: "Add The lesson" }));
    await user.type(screen.getByLabelText("The lesson"), "Ship in small steps.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(slot("slot-learning-lesson-x")).toHaveTextContent("Ship in small steps."));
    expect(patches).toEqual([
      { slots: [{ section: "learning", slot: "lesson", step: null, text: "Ship in small steps.", skipped: false }] },
    ]);
    expect(slot("slot-learning-lesson-x")).toHaveTextContent("Your words");
    // Ready needs a why on a step too; add it, and the status steps move to Ready.
    await user.click(within(section("action")).getByRole("button", { name: "Add Step 1: Why you did it" }));
    await user.type(screen.getByLabelText("Step 1: Why you did it"), "Rollback had to be fast.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByTestId("story-status")).toHaveTextContent("Ready"));
    expect(screen.getByRole("list", { name: "Status steps" }).querySelector("[aria-current=step]")).toHaveTextContent("Ready");
  });

  it("SC-10: steps are added, moved and removed, up to five", async () => {
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    const steps = () => screen.getAllByTestId("outline-step");
    for (let n = 2; n <= 5; n++) {
      await user.click(screen.getByRole("button", { name: "Add a step" }));
      await waitFor(() => expect(steps()).toHaveLength(n));
    }
    expect(screen.queryByRole("button", { name: "Add a step" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Move step 1 down" }));
    await waitFor(() => expect(steps()[1]).toHaveTextContent("I split the rollout by country."));
    await user.click(screen.getByRole("button", { name: "Remove step 2" }));
    await waitFor(() => expect(steps()).toHaveLength(4));
    expect(screen.queryByText("I split the rollout by country.")).not.toBeInTheDocument();
  });

  it("SC-10: an empty optional slot opens from the quiet line, and an empty slot can be marked skipped", async () => {
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(within(section("task")).getByRole("button", { name: "Your goal or responsibility" }));
    await user.click(screen.getByRole("button", { name: "Mark as skipped" }));
    await waitFor(() => expect(slot("slot-task-goal-x")).toHaveTextContent("Skipped"));
  });
});

describe("SC-11 (UI): Improve with Strova", () => {
  it("SC-11: edits show before and after, with Accept or Reject", async () => {
    const accepts = requests("POST", "/improve/accept");
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(within(section("situation")).getByRole("button", { name: "Improve with Strova" }));
    const panel = screen.getByRole("region", { name: "Improve Situation with Strova" });
    await user.type(within(panel).getByLabelText("A note for Strova (optional)"), "Shorter");
    await user.click(within(panel).getByRole("button", { name: "Improve Situation" }));
    const edit = await within(panel).findByRole("group", { name: "Edit to Your role at the time" });
    expect(within(edit).getByText("I was the tech lead on checkout.", { selector: "del" })).toBeInTheDocument();
    await user.click(within(edit).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(accepts).toHaveLength(1));
    expect(accepts[0]).toMatchObject({ note: "Shorter", edits: [expect.objectContaining({ slot: "role" })] });
    expect(await within(panel).findByRole("status")).toHaveTextContent("Situation is up to date.");
  });

  it("SC-11: questions say which facts are missing and open a session with Strova", async () => {
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(within(section("learning")).getByRole("button", { name: "Improve with Strova" }));
    await user.click(screen.getByRole("button", { name: "Improve Learning" }));
    const questions = await screen.findByTestId("improve-questions");
    expect(questions).toHaveTextContent("What did you do yourself");
    expect(within(questions).getByRole("link", { name: "Answer with Strova" })).toHaveAttribute(
      "href",
      expect.stringContaining("story=s1"),
    );
  });
});

describe("SC-12 (UI): Switch to STAR or CARL", () => {
  it("SC-12: a switch without rewrite saves at once and keeps every slot", async () => {
    renderStory("s1");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Switch to CARL" }));
    await waitFor(() => expect(screen.getByTestId("story-style")).toHaveTextContent("CARL"));
    expect(screen.getAllByTestId("outline-section").map((s) => s.dataset.section)).toEqual([
      "challenge",
      "action",
      "result",
      "learning",
    ]);
    expect(slot("slot-challenge-role-x")).toHaveTextContent("I was the tech lead on checkout.");
    expect(slot("slot-challenge-org-x")).toHaveTextContent("Skipped");
  });

  it("SC-12: Rewrite the wording too shows a preview to accept or discard", async () => {
    renderStory("s2");
    await screen.findByTestId("outline-story");
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Rewrite the wording too"));
    await user.click(screen.getByRole("button", { name: "Switch to STAR" }));
    const preview = await screen.findByRole("region", { name: "STAR preview" });
    expect(screen.getByTestId("story-style")).toHaveTextContent("CARL"); // nothing saved yet
    await user.click(within(preview).getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("region", { name: "STAR preview" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Switch to STAR" }));
    await user.click(within(await screen.findByRole("region", { name: "STAR preview" })).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(screen.getByTestId("story-style")).toHaveTextContent("STAR"));
  });
});

describe("SC-13 (UI): Organize with Strova", () => {
  it("SC-13: a classic story keeps its parts and previews Organize before anything changes", async () => {
    renderStory("c1");
    expect(await screen.findByRole("region", { name: "Organize with Strova" })).toBeInTheDocument();
    expect(screen.queryByTestId("outline-story")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Story parts" })).toHaveTextContent("The platform team refused");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Organize with Strova" }));
    const preview = await screen.findByRole("region", { name: "Organized preview" });
    expect(within(preview).getByTestId("outline-preview")).toHaveTextContent("The platform team refused");
    await user.click(within(preview).getByRole("button", { name: "Discard" }));
    expect(screen.queryByTestId("outline-story")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Organize with Strova" }));
    await user.click(within(await screen.findByRole("region", { name: "Organized preview" })).getByRole("button", { name: "Accept" }));
    expect(await screen.findByTestId("outline-story")).toBeInTheDocument();
    expect(screen.getByTestId("story-style")).toHaveTextContent("STAR");
    expect(screen.queryByRole("region", { name: "Organize with Strova" })).not.toBeInTheDocument();
  });
});

describe("Review with Strova on a styled story", () => {
  it("ST-11, SC-11: the review page shows the story's sections, read-only", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/stories/s2/review"]}>
          <Routes>
            <Route path="/stories/:storyId/review" element={<V2Only><ReviewPage /></V2Only>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const sections = await screen.findByRole("region", { name: "Story sections" });
    expect(within(sections).getByTestId("outline-preview")).toHaveTextContent("I was the tech lead on checkout.");
    expect(within(sections).queryByRole("button", { name: /Edit|Add/ })).not.toBeInTheDocument();
    expect(within(sections).getAllByTestId("outline-section").map((s) => s.dataset.section)).toEqual([
      "challenge",
      "action",
      "result",
      "learning",
    ]);
  });
});
