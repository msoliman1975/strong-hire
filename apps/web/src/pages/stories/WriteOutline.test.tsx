/**
 * SC-1, SC-10 (UI): Write it yourself in STAR or CARL, with MSW (mocks/storyHandlers.ts and
 * outlineMock.ts, the shapes of POST /stories with `style` and `slots`).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { server } from "../../mocks/node";
import { mockStoryLibrary, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { NewStoryPage } from "./NewStoryPage";
import { V2Only } from "./V2Only";

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories([]);
});
afterEach(() => setFeatureOverrides({}));

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function renderNew() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/stories/new"]}>
        <Routes>
          <Route path="/stories/new" element={<V2Only><NewStoryPage /></V2Only>} />
          <Route path="/stories" element={<p>Stories</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function posted(): unknown[] {
  const bodies: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.method === "POST" && new URL(request.url).pathname.endsWith("/stories")) {
      bodies.push(await request.clone().json());
    }
  });
  return bodies;
}

describe("SC-1, SC-10 (UI): write it yourself in STAR or CARL", () => {
  it("SC-1: STAR is preselected, CARL and the five free-text parts are offered", () => {
    renderNew();
    expect(screen.getByRole("radio", { name: /^STAR/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^CARL/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Five free-text parts/ })).toBeInTheDocument();
    const outline = screen.getByTestId("write-outline");
    expect(within(outline).getAllByRole("group").map((g) => g.getAttribute("aria-label") ?? g.querySelector("legend")?.textContent)).toEqual(
      expect.arrayContaining(["Situation", "Task", "Action", "Result", "Learning"]),
    );
    expect(screen.getByRole("textbox", { name: /Your role at the time/ })).toBeInTheDocument();
    expect(screen.getByText("Your role at the time").closest("label")).toHaveTextContent("needed for Ready");
  });

  it("SC-10: the typed slots are saved as the story's outline, in the user's words", async () => {
    const bodies = posted();
    renderNew();
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Story title" }), "Checkout migration");
    await user.type(screen.getByRole("textbox", { name: /Your role at the time/ }), "I was the **tech lead**.");
    await user.type(screen.getByRole("textbox", { name: /^Step 1: What you did/ }), "I split the rollout.");
    await user.click(screen.getByRole("button", { name: "Add a step" }));
    await user.type(screen.getByRole("textbox", { name: /^Step 2: What you did/ }), "I ran a daily check-in.");
    await user.type(screen.getByRole("textbox", { name: /A metric, before and after/ }), "Errors fell.");
    await user.type(screen.getByLabelText("After"), "0.3%");
    await user.click(screen.getByRole("button", { name: "Save as a Draft" }));
    await expect.poll(() => screen.getByTestId("where").textContent).toBe("/stories");
    expect(bodies[0]).toMatchObject({
      title: "Checkout migration",
      style: "star",
      slots: [
        { section: "situation", slot: "role", step: null, text: "I was the **tech lead**." },
        { section: "action", slot: "did", step: 0, text: "I split the rollout." },
        { section: "action", slot: "did", step: 1, text: "I ran a daily check-in." },
        { section: "result", slot: "metric", step: null, text: "Errors fell.", after: "0.3%" },
      ],
    });
    const [story] = mockStoryLibrary();
    expect(story.style).toBe("star");
    expect(story.context).toBe("I was the tech lead.");
  });

  it("SC-1: CARL shows its own sections; Task slots sit in Challenge", async () => {
    renderNew();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: /^CARL/ }));
    const legends = [...screen.getByTestId("write-outline").querySelectorAll("legend")].map((l) => l.textContent);
    expect(legends).toEqual(["Challenge", "Action", "Result", "Learning"]);
    expect(screen.getByRole("textbox", { name: /Your goal or responsibility/ })).toBeInTheDocument();
  });

  it("SC-10: steps go up to five and the last one can be removed", async () => {
    renderNew();
    const user = userEvent.setup();
    for (let i = 0; i < 4; i++) await user.click(screen.getByRole("button", { name: "Add a step" }));
    expect(screen.queryByRole("button", { name: "Add a step" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Step 5" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove step 5" }));
    expect(screen.queryByRole("group", { name: "Step 5" })).not.toBeInTheDocument();
  });
});
