/**
 * SC-8, SC-9 (UI): flow flags and skill hints on the story page, with MSW (mocks/outlineMock.ts,
 * the shapes of strong_api.stories.flow). Both are advisory and never change the status.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { renderLegacy } from "../../mocks/craftMock";
import { MOCK_HINTS, mockOutline } from "../../mocks/outlineMock";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { StoryPage } from "./StoryPage";
import { V2Only } from "./V2Only";

function readyOutline() {
  const outline = mockOutline("star");
  const learning = outline.sections.find((s) => s.section === "learning")!;
  learning.slots.lesson = { text: "Ship in small steps.", quotes: [], by_user: true, status: "filled" };
  const action = outline.sections.find((s) => s.section === "action")!;
  action.steps![0].why = { text: "Rollback had to be fast.", quotes: [], by_user: true, status: "filled" };
  return outline;
}

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  const outline = readyOutline();
  resetMockStories([
    mockStory({
      id: "s1",
      title: "Checkout migration",
      style: "star",
      outline,
      ...renderLegacy(outline),
      skills: ["ownership"],
      hints: structuredClone(MOCK_HINTS),
    }),
  ]);
});
afterEach(() => setFeatureOverrides({}));

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderStory() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/stories/s1"]}>
        <Routes>
          <Route path="/stories/:storyId" element={<V2Only><StoryPage /></V2Only>} />
          <Route path="/coach/new" element={<p>Coach</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SC-9 (UI): flow flags", () => {
  it("SC-9: Check the flow shows one flag of each type, each with Ask me about it and Dismiss; the status stays", async () => {
    renderStory();
    await screen.findByTestId("outline-story");
    expect(screen.getByTestId("story-status")).toHaveTextContent("Ready");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Check the flow" }));
    const flags = await screen.findAllByTestId("flow-flag");
    expect(flags.map((f) => f.dataset.type).sort()).toEqual([
      "action_vs_problem",
      "loose_end",
      "number_conflict",
      "result_vs_problem",
      "timeline_conflict",
    ]);
    expect(within(flags[0]).getByText(/^Situation: /)).toBeInTheDocument();
    expect(screen.getByTestId("story-status")).toHaveTextContent("Ready");
    const first = flags[0];
    const question = within(first).getByText(/\?$/).textContent ?? "";
    await user.click(within(first).getByRole("button", { name: `Dismiss: ${question}` }));
    await waitFor(() => expect(screen.getAllByTestId("flow-flag")).toHaveLength(4));
    expect(screen.getByTestId("story-status")).toHaveTextContent("Ready");
    await user.click(within(screen.getAllByTestId("flow-flag")[0]).getByRole("button", { name: /^Ask me about it/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/coach/new?story=s1");
  });
});

describe("SC-8 (UI): skill hints", () => {
  it("SC-8: hints offer Deepen, which opens a short session for the skill, and Not now", async () => {
    renderStory();
    const hints = await screen.findAllByTestId("skill-hint");
    expect(hints.map((h) => h.textContent)).toEqual([
      expect.stringContaining("Collaboration"),
      expect.stringContaining("Judgment"),
    ]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Not now: Judgment" }));
    await waitFor(() => expect(screen.getAllByTestId("skill-hint")).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Deepen Collaboration" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/coach/new?story=s1&skill=collaboration"));
  });
});
