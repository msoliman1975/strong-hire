/** ST-5 (UI): the story fit table on the plan page, with MSW. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { server } from "../../mocks/node";
import { mockStoryFit } from "../../mocks/storyFitHandlers";
import { StoryFitTable, type StoryFitView } from "./StoryFitTable";

function renderTable(view: StoryFitView) {
  server.use(http.get("*/api/plan/:jobId/:resumeId/story-fit", () => HttpResponse.json(view)));
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/interviews/j1/r1"]}>
        <Routes>
          <Route path="/interviews/:jobId/:resumeId" element={<StoryFitTable jobId="j1" resumeId="r1" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("story fit table", () => {
  it("ST-5: one row per tested skill with the best story and a strong, thin or missing mark", async () => {
    renderTable(mockStoryFit);
    const table = await screen.findByTestId("story-fit");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);

    const [ownership, impact] = rows;
    expect(within(ownership).getByRole("rowheader")).toHaveTextContent("Ownership");
    expect(within(ownership).getByRole("link", { name: "Payments outage" })).toHaveAttribute("href", "/stories/story-1");
    expect(within(ownership).getByText("Strong")).toBeInTheDocument();
    expect(within(impact).getByText("Thin")).toBeInTheDocument();
    expect(within(impact).getByText("The result has no number yet.")).toBeInTheDocument();
  });

  it("ST-5: a missing story opens a coach session for that skill and interview", async () => {
    renderTable(mockStoryFit);
    const table = await screen.findByTestId("story-fit");
    const conflict = within(table).getAllByRole("row")[3];
    expect(within(conflict).getByText("Missing")).toBeInTheDocument();
    expect(within(conflict).getByRole("link", { name: "Build it with the coach" })).toHaveAttribute(
      "href",
      "/coach/new?skill=conflict_handling&job=j1",
    );
  });

  it("ST-5: while the worker is still matching, the page says so", async () => {
    renderTable({ status: "computing", rows: [], computed_at: null });
    expect(await screen.findByText("Matching your stories to the skills")).toBeInTheDocument();

    renderTable({ ...mockStoryFit, status: "computing" });
    expect(await screen.findByText("Still matching the other skills.")).toBeInTheDocument();
  });
});
