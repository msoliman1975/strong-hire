/**
 * SC-1 (UI), SC-7, SC-17: crafting a styled story. The start screen's STAR or CARL choice, the
 * outline panel live beside the conversation, and the reply box (grows, Expand, quick replies),
 * with MSW (mocks/coachHandlers.ts and mocks/craftMock.ts, the shapes of strong_api.coach).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { resetMockCoach } from "../../mocks/coachHandlers";
import { server } from "../../mocks/node";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { V2Only } from "../stories/V2Only";
import { CoachSessionPage } from "./CoachSessionPage";
import { CoachStartPage } from "./CoachStartPage";
import { outlineReady, type StoryOutline } from "./outline";
import { ReplyBox } from "./ReplyBox";

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories([mockStory({ id: "s1", title: "Checkout migration", context: "A thing." })]);
  resetMockCoach();
});
afterEach(() => setFeatureOverrides({}));

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/stories" element={<p>Stories</p>} />
          <Route path="/coach/new" element={<V2Only><CoachStartPage /></V2Only>} />
          <Route path="/coach/:sessionId" element={<V2Only><CoachSessionPage /></V2Only>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function startBodies(): unknown[] {
  const started: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.method === "POST" && request.url.endsWith("/coach/sessions")) started.push(await request.clone().json());
  });
  return started;
}

const sectionState = () =>
  Object.fromEntries(
    screen.getAllByTestId("craft-section").map((li) => [li.dataset.section, li.dataset.current ? "now" : "-"]),
  );
const slot = (id: string) => screen.getAllByTestId("craft-slot").find((li) => li.dataset.slot === id);

async function send(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your reply"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

describe("SC-1 (UI): the style picker", () => {
  it("SC-1: a new story offers STAR and CARL with Strova's suggestion preselected", async () => {
    const started = startBodies();
    renderAt("/coach/new?skill=conflict_handling&job=j1");
    expect(await screen.findByRole("heading", { level: 1, name: "How do you want to tell it?" })).toBeInTheDocument();
    expect(await screen.findByTestId("style-suggestion")).toHaveTextContent(
      "Strova suggests CARL for a conflict handling story.",
    );
    const carl = screen.getByRole("radio", { name: /CARL/ });
    const star = screen.getByRole("radio", { name: /STAR/ });
    expect(carl).toBeChecked();
    expect(star).not.toBeChecked();
    expect(screen.getByText("Situation · Task · Action · Result · Learning")).toBeInTheDocument();
    expect(started).toEqual([]); // nothing starts until the user picks
    const user = userEvent.setup();
    await user.click(star);
    await user.click(screen.getByRole("button", { name: "Start crafting" }));
    await screen.findByTestId("craft-panel");
    expect(started).toEqual([
      expect.objectContaining({ story_style: "star", target_skill: "conflict_handling", job_target_id: "j1" }),
    ]);
  });

  it("SC-1: STAR is suggested for other skills, and ?style= starts at once", async () => {
    renderAt("/coach/new?skill=collaboration");
    expect(await screen.findByRole("radio", { name: /STAR/ })).toBeChecked();
    expect(await screen.findByTestId("style-suggestion")).toHaveTextContent("Strova suggests STAR");
  });

  it("SC-1: an existing story starts at once in its own style, with no picker", async () => {
    const started = startBodies();
    renderAt("/coach/new?story=s1");
    expect(await screen.findByRole("heading", { level: 1, name: "Checkout migration" })).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(started).toEqual([expect.objectContaining({ story_id: "s1", story_style: null })]);
    expect(screen.queryByTestId("craft-panel")).not.toBeInTheDocument(); // classic stays classic
    expect(screen.getAllByTestId("coach-part")).toHaveLength(5);
  });
});

describe("SC-7 (UI): the outline panel", () => {
  it("SC-7: the outline fills live, slot by slot, with the section in progress highlighted", async () => {
    renderAt("/coach/new?style=star");
    await screen.findByTestId("craft-panel");
    expect(sectionState()).toEqual({ situation: "now", task: "-", action: "-", result: "-", learning: "-" });
    expect(slot("situation.org")).toHaveAttribute("data-asking", "true");
    expect(slot("situation.org")).toHaveTextContent("Strova is asking");
    expect(slot("situation.role")).toHaveTextContent("Empty · needed for Ready");
    expect(screen.getByText(/Also, if you have them: Constraints/)).toBeInTheDocument();

    await send("Acme, on the payments team");
    await waitFor(() => expect(slot("situation.org")).toHaveAttribute("data-state", "filled"));
    expect(slot("situation.org")).toHaveTextContent("Acme, on the payments team");
    expect(slot("situation.role")).toHaveAttribute("data-asking", "true");
  });

  it("SC-5, SC-7: Skip this marks the slot skipped, in text, and Move on opens the next section", async () => {
    renderAt("/coach/new?style=star");
    await screen.findByTestId("craft-panel");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Skip this" }));
    await waitFor(() => expect(slot("situation.org")).toHaveAttribute("data-state", "skipped"));
    expect(slot("situation.org")).toHaveTextContent("Skipped");
    await user.click(screen.getByRole("button", { name: "Move on" }));
    await waitFor(() => expect(sectionState().task).toBe("now"));
    expect(sectionState().situation).toBe("-");
    const turns = screen.getAllByTestId("coach-turn");
    expect(turns.at(-1)).toHaveTextContent("What were you responsible for");
  });

  it("SC-3, SC-7: the Ready state shows once the core slots are filled", async () => {
    renderAt("/coach/new?style=carl");
    await screen.findByTestId("craft-panel");
    const user = userEvent.setup();
    // Challenge: skip org, then role, skip scale and timeframe, problem, skip stakeholders.
    await user.click(screen.getByRole("button", { name: "Skip this" }));
    await send("I was the tech lead");
    for (let i = 0; i < 2; i++) await user.click(await screen.findByRole("button", { name: "Skip this" }));
    await send("The migration was two weeks late");
    await user.click(await screen.findByRole("button", { name: "Skip this" }));
    await send("I split the rollout by country");
    await send("Rollback had to be fast");
    await send("Errors fell from 2% to 0.3%");
    expect(screen.queryByText(/saved your story as Ready/)).not.toBeInTheDocument();
    await send("Ship in small reversible steps");
    expect(await screen.findByText(/Every core slot is filled/)).toBeInTheDocument();
    expect(within(screen.getByTestId("craft-panel")).getByText(/CARL story · Ready/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Quick replies" })).not.toBeInTheDocument(); // all done
  }, 20_000); // ten typed turns

  it("SC-3: Ready needs exactly the core slots", () => {
    const filled = (text: string) => ({ text, quotes: [], by_user: true, status: "filled" as const });
    const outline = {
      style: "star",
      sections: [
        { section: "situation", slots: { role: filled("r"), problem: filled("p") }, steps: null, metric: null },
        { section: "task", slots: {}, steps: null, metric: null },
        {
          section: "action",
          slots: {},
          steps: [{ did: filled("d"), why: null, alternatives: null, people: null }, { did: null, why: filled("w"), alternatives: null, people: null }],
          metric: null,
        },
        { section: "result", slots: {}, steps: null, metric: { ...filled("m"), before: null, after: null, unit: null } },
        { section: "learning", slots: { lesson: filled("l") }, steps: null, metric: null },
      ],
    } as StoryOutline;
    expect(outlineReady(outline)).toBe(true);
    const noLesson = structuredClone(outline);
    noLesson.sections[4].slots = {};
    expect(outlineReady(noLesson)).toBe(false);
  });
});

describe("SC-17 (UI): the reply box", () => {
  function Box({ onSend = () => undefined, onQuick = () => undefined }: { onSend?: () => void; onQuick?: (t: string) => void }) {
    const [value, setValue] = useState("");
    return <ReplyBox value={value} onChange={setValue} onSend={onSend} onQuick={onQuick} busy={false} quick />;
  }

  it("SC-17: the box grows with the text up to half the screen, then scrolls", async () => {
    const heights = { scroll: 120 };
    Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
      configurable: true,
      get: () => heights.scroll,
    });
    window.innerHeight = 800;
    render(<Box />);
    const box = screen.getByLabelText("Your reply") as HTMLTextAreaElement;
    const user = userEvent.setup();
    await user.type(box, "a");
    expect(box.style.height).toBe("120px");
    expect(box.style.overflowY).toBe("hidden");
    heights.scroll = 900;
    await user.type(box, "b");
    expect(box.style.height).toBe("400px");
    expect(box.style.overflowY).toBe("auto");
  });

  it("SC-17: Enter sends, Shift+Enter adds a line", async () => {
    const sent: string[] = [];
    render(<Box onSend={() => sent.push("sent")} />);
    const box = screen.getByLabelText("Your reply") as HTMLTextAreaElement;
    const user = userEvent.setup();
    await user.type(box, "one{Shift>}{Enter}{/Shift}two");
    expect(box.value).toBe("one\ntwo");
    expect(sent).toEqual([]);
    await user.type(box, "{Enter}");
    expect(sent).toEqual(["sent"]);
  });

  it("SC-17: Expand opens a full-width writing view; Esc returns with the text kept", async () => {
    render(<Box />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your reply"), "Draft");
    await user.click(screen.getByRole("button", { name: "Expand" }));
    const dialog = screen.getByRole("dialog", { name: "Write your reply" });
    const big = within(dialog).getByLabelText("Your reply");
    expect(big).toHaveFocus();
    expect(big).toHaveValue("Draft");
    await user.type(big, " and more");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your reply")).toHaveValue("Draft and more");
    await waitFor(() => expect(screen.getByRole("button", { name: "Expand" })).toHaveFocus());
  });

  it("SC-5, SC-17: the quick replies send skip and move on", async () => {
    const quick: string[] = [];
    render(<Box onQuick={(t) => quick.push(t)} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Skip this" }));
    await user.click(screen.getByRole("button", { name: "Move on" }));
    expect(quick).toEqual(["skip", "move on"]);
  });
});

