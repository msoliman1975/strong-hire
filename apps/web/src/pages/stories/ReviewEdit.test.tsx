/**
 * ST-11 (A, B): Review with Strova says when it is finished and when every note is done, and each
 * note offers Edit, which opens the part (or a styled story's section) with Strova's note as
 * guidance. With MSW (mocks/suggestionHandlers.ts: a result edit and a reflection note).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { renderLegacy } from "../../mocks/craftMock";
import { mockOutline } from "../../mocks/outlineMock";
import { mockStory, mockStoryLibrary, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { ReviewPage } from "./ReviewPage";
import { StoryPage } from "./StoryPage";
import { V2Only } from "./V2Only";

const CLASSIC = mockStory({ id: "c1", title: "Pushback", context: "The platform team said no.", result: "The migration went well." });

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  const outline = mockOutline("star");
  resetMockStories([CLASSIC, mockStory({ id: "s1", title: "Checkout", style: "star", outline, ...renderLegacy(outline) })]);
});
afterEach(() => setFeatureOverrides({}));

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/stories/:storyId/review" element={<V2Only><ReviewPage /></V2Only>} />
          <Route path="/stories/:storyId" element={<V2Only><StoryPage /></V2Only>} />
          <Route path="/coach/new" element={<p>Coach</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function review(path: string) {
  const user = userEvent.setup();
  renderAt(path);
  await user.click(await screen.findByRole("button", { name: "Review with Strova" }));
  const panel = screen.getByRole("region", { name: "Strova's review" });
  await within(panel).findByTestId("review-done");
  return { user, panel };
}

describe("ST-11 (A): Strova says when she is done", () => {
  it("ST-11: the panel announces that Strova has finished, with the notes to work through", async () => {
    const { panel } = await review("/stories/c1/review");
    const done = within(panel).getByTestId("review-done");
    expect(done).toHaveAttribute("role", "status");
    expect(done).toHaveTextContent("Strova has finished reviewing your story. 2 notes, 1 with a suggested edit.");
    expect(within(panel).getByTestId("review-progress")).toHaveTextContent("0 of 2 notes done.");
  });

  it("ST-11: when every note is done, the page says so", async () => {
    const { user, panel } = await review("/stories/c1/review");
    await user.click(within(within(panel).getByRole("group", { name: "Edit to Result" })).getByRole("button", { name: "Accept" }));
    await within(panel).findByText("Result updated.");
    expect(within(panel).getByTestId("review-progress")).toHaveTextContent("1 of 2 notes done.");
    await user.click(within(within(panel).getByRole("group", { name: "Note on Reflection" })).getByRole("button", { name: "Skip" }));
    expect(within(panel).getByTestId("review-all-done")).toHaveTextContent("You've worked through every note.");
    expect(within(panel).getByTestId("review-progress")).toHaveTextContent("Every note done.");
  });

  it("ST-11: the story page says when a review is ready", async () => {
    await review("/stories/c1/review");
    renderAt("/stories/c1");
    const ready = await screen.findByTestId("review-ready");
    expect(ready).toHaveTextContent("Strova's review is ready.");
    expect(within(ready).getByRole("link", { name: "Open the review" })).toHaveAttribute("href", "/stories/c1/review");
  });
});

describe("ST-11 (B): Edit with Strova's guidance", () => {
  it("ST-11: Edit opens the part with the note as guidance; Save updates the story", async () => {
    const { user, panel } = await review("/stories/c1/review");
    await user.click(within(panel).getByRole("button", { name: "Edit Reflection" }));
    const editor = within(panel).getByRole("form", { name: "Edit Reflection" });
    expect(within(editor).getByTestId("review-guidance")).toHaveTextContent("Say what you would do differently next time.");
    await user.type(within(editor).getByRole("textbox", { name: "Reflection" }), "Next time I would ask the platform team sooner.");
    await user.click(within(editor).getByRole("button", { name: "Save Reflection" }));
    await within(panel).findByText("Reflection edited.");
    await waitFor(() => expect(mockStoryLibrary().find((s) => s.id === "c1")?.reflection).toBe("Next time I would ask the platform team sooner."));
  });

  it("ST-11: a suggested edit can be the starting text, then changed before saving", async () => {
    const { user, panel } = await review("/stories/c1/review");
    await user.click(within(panel).getByRole("button", { name: "Edit Result" }));
    const editor = within(panel).getByRole("form", { name: "Edit Result" });
    expect(within(editor).getByTestId("review-guidance")).toHaveTextContent("Her suggestion, from your words:");
    const box = within(editor).getByRole("textbox", { name: "Result" });
    expect(box).toHaveValue("The migration went well.");
    await user.click(within(editor).getByRole("button", { name: "Start from her suggestion" }));
    expect(box).toHaveValue("We finished a week before Black Friday and not one payment failed.");
    await user.click(within(editor).getByRole("button", { name: "Cancel" }));
    expect(within(panel).getByRole("group", { name: "Edit to Result" })).toBeInTheDocument();
  });

  it("ST-11, SC-10: on a styled story, Edit opens the section's slots with the note as guidance", async () => {
    const { user, panel } = await review("/stories/s1/review");
    expect(within(panel).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument(); // notes only
    await user.click(within(panel).getByRole("button", { name: "Edit Learning" }));
    const editor = within(panel).getByRole("group", { name: "Edit Learning" });
    expect(within(editor).getByTestId("review-guidance")).toHaveTextContent("Say what you would do differently next time.");
    await user.click(within(editor).getByRole("button", { name: "Add The lesson" }));
    await user.type(within(editor).getByRole("textbox", { name: "The lesson" }), "Ask the platform team sooner.");
    await user.click(within(editor).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockStoryLibrary().find((s) => s.id === "s1")?.reflection).toBe("Ask the platform team sooner."));
    await user.click(within(editor).getByRole("button", { name: "Done with Learning" }));
    expect(await within(panel).findByText("Learning edited.")).toBeInTheDocument();
  });
});
