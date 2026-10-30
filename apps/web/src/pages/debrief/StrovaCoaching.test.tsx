/**
 * U09: Strova's coaching on the v2 debrief (DB-4), the Proven celebration (DB-5), the plan line
 * (DB-6) and the suggestions' actions (SG-8 UI): Apply then Undo, Edit first, Dismiss, Save as a
 * story, Craft it with Strova. The suggestions are the U08 mock samples.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { Debrief, Scorecard } from "../../api/types";
import { createQueryClient } from "../../App";
import { mockAnswersAtBar } from "../../mocks/debrief";
import { scorecardFor } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { debriefSuggestions } from "../../mocks/suggestionHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { DebriefPage } from "../DebriefPage";
import { coachingLine } from "./StrovaCoaching";

const CHECKOUT = "11111111-1111-4111-8111-111111111111"; // the story mocks' Proven seed story

afterEach(() => {
  setFeatureOverrides({});
  server.events.removeAllListeners();
});

function debrief(changes: Partial<Debrief> = {}, card: Scorecard = scorecardFor("behavioral", true)): Debrief {
  return {
    session: {
      id: "s2",
      job_target_id: "j1",
      config: {
        interview_type: "behavioral",
        difficulty: "realistic",
        mode: "realistic",
        duration_min: 30,
        level: "senior",
        custom: null,
        tone: "as_company",
      },
      status: "completed",
      started_at: "2026-10-05T10:00:00Z",
      ended_at: "2026-10-05T10:30:00Z",
      minutes_billed: 30,
      failure_reason: null,
    },
    status: "ready",
    scorecard: card,
    next_session: null,
    next_custom_session: null,
    generic_mode: true,
    company_name: "Example Corp",
    company_slug: null,
    values_framework: null,
    questions: [],
    previous_signal: null,
    answers_at_bar: mockAnswersAtBar(card),
    suggestions: debriefSuggestions("s2", "j1"),
    next_plan_item: null,
    ...changes,
  };
}

function renderDebrief(body: Debrief) {
  setFeatureOverrides({ v2_enabled: true });
  const accepted: unknown[] = [];
  server.use(
    http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(body)),
    http.get("*/api/sessions/:sessionId/feedback", () => HttpResponse.json(null)),
  );
  server.events.on("request:start", async ({ request }) => {
    if (request.method === "POST" && request.url.includes("/accept")) accepted.push(await request.clone().json());
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s2/debrief"]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, accepted };
}

async function coaching() {
  return screen.findByRole("region", { name: "Strova's coaching" });
}

describe("Strova's coaching", () => {
  it("DB-4: follows the answers, back on your side, with this take's suggestions", async () => {
    renderDebrief(debrief());
    const card = await coaching();
    const answers = screen.getByRole("region", { name: "Answer by answer" });
    expect(answers.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(card).getByRole("img", { name: "Strova is coaching" })).toHaveAttribute("width", "72");
    expect(card).toHaveTextContent("Back on your side: what to do next");
    expect(card).toHaveTextContent("Here is what I suggest:");
    expect(await within(card).findByRole("group", { name: "Tune a story: Checkout migration" })).toBeInTheDocument();
    expect(within(card).getByRole("group", { name: /^New story: / })).toBeInTheDocument();
    const missing = within(card).getByRole("group", { name: "Missing skill: Conflict handling" });
    expect(within(missing).getByRole("link", { name: "Craft it with Strova" })).toHaveAttribute(
      "href",
      "/coach/new?skill=conflict_handling&job=j1",
    );
  });

  it("DB-4: the coaching sentence names the strongest skill and the one to work on", () => {
    const card = scorecardFor("behavioral", true);
    const line = coachingLine({
      ...card,
      competency_scores: [
        { ...card.competency_scores[0], competency: "ownership", score: 4 },
        { ...card.competency_scores[0], competency: "conflict_handling", score: 2 },
      ],
    });
    expect(line).toBe("You showed ownership. Next, work on conflict handling. Here is what I suggest:");
  });

  it("SG-8: Apply sets the edit, then Undo restores it", async () => {
    const { user, accepted } = renderDebrief(debrief());
    const card = await coaching();
    const tune = await within(card).findByRole("group", { name: "Tune a story: Checkout migration" });
    expect(tune).toHaveTextContent("The migration went well.");
    expect(tune).toHaveTextContent("We finished a week before Black Friday and not one payment failed.");
    await user.click(within(tune).getByRole("button", { name: "Apply" }));
    const notice = await within(card).findByTestId("applied");
    expect(notice).toHaveTextContent("Applied to “Checkout migration”.");
    expect(within(notice).getByRole("link", { name: "See the story" })).toHaveAttribute("href", `/stories/${CHECKOUT}`);
    expect(accepted).toEqual([{}]);
    await user.click(within(notice).getByRole("button", { name: "Undo" }));
    expect(await within(card).findByRole("group", { name: "Tune a story: Checkout migration" })).toBeInTheDocument();
  });

  it("SG-8: Edit first lets you change the text, and Apply my edit sends it", async () => {
    const { user, accepted } = renderDebrief(debrief());
    const tune = await within(await coaching()).findByRole("group", { name: "Tune a story: Checkout migration" });
    await user.click(within(tune).getByRole("button", { name: "Edit first" }));
    const box = within(tune).getByRole("textbox", { name: "Result" });
    expect(box).toHaveValue("We finished a week before Black Friday and not one payment failed.");
    await user.clear(box);
    await user.type(box, "We finished early and not one payment failed.");
    await user.click(within(tune).getByRole("button", { name: "Apply my edit" }));
    expect(await screen.findByTestId("applied")).toBeInTheDocument();
    expect(accepted).toEqual([{ after: "We finished early and not one payment failed." }]);
  });

  it("SG-8: Dismiss removes a suggestion; Save as a story saves the new story", async () => {
    const { user } = renderDebrief(debrief());
    const card = await coaching();
    const missing = await within(card).findByRole("group", { name: "Missing skill: Conflict handling" });
    await user.click(within(missing).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(within(card).queryByRole("group", { name: /^Missing skill/ })).toBeNull());
    const fresh = within(card).getByRole("group", { name: /^New story: / });
    await user.click(within(fresh).getByRole("button", { name: "Save as a story" }));
    expect(await within(card).findByText(/as a Draft story\./)).toBeInTheDocument();
  });

  it("DB-5: a story this Realistic take made Proven is celebrated with the celebrating avatar", async () => {
    const base = scorecardFor("behavioral", true);
    const card: Scorecard = {
      ...base,
      per_question: base.per_question.map((q, i) => (i === 0 ? { ...q, story_id: CHECKOUT } : q)),
    };
    renderDebrief(debrief({}, card));
    const proven = await within(await coaching()).findByTestId("proven");
    expect(proven).toHaveTextContent("Checkout migration is now Proven.");
    expect(within(proven).getByRole("img", { name: "Strova is celebrating" })).toBeInTheDocument();
  });

  it("DB-5: a Practice take never shows the Proven notice", async () => {
    const base = scorecardFor("behavioral", true);
    const card: Scorecard = {
      ...base,
      per_question: base.per_question.map((q, i) => (i === 0 ? { ...q, story_id: CHECKOUT } : q)),
    };
    const body = debrief({}, card);
    body.session.config.mode = "coach";
    renderDebrief(body);
    await coaching();
    await screen.findByRole("link", { name: "Checkout migration" });
    expect(screen.queryByTestId("proven")).toBeNull();
  });

  it("DB-6: the plan line says what is next, and hides until the plan has an item", async () => {
    renderDebrief(debrief({ next_plan_item: "the Hiring manager take on Saturday." }));
    const line = await within(await coaching()).findByTestId("plan-line");
    expect(line).toHaveTextContent("Your plan updated: next is the Hiring manager take on Saturday.");
    expect(within(line).getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
  });

  it("DB-6: no plan item, no plan line", async () => {
    renderDebrief(debrief());
    await coaching();
    expect(screen.queryByTestId("plan-line")).toBeNull();
  });
});
