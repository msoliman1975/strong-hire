/** ST-6 and ST-2 (UI): the story used per answer, "Save as a story" and the library updates card. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { Debrief } from "../../api/types";
import { createQueryClient } from "../../App";
import { mockAnswersAtBar } from "../../mocks/debrief";
import { scorecardFor, sessionPlan } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { DebriefPage } from "../DebriefPage";
import type { Story } from "./StoryApi";

afterEach(() => setFeatureOverrides({}));

const T = "2026-10-05T10:31:00Z";

function story(over: Partial<Story>): Story {
  return {
    id: "st1",
    title: "Invoice cutover",
    context: null,
    stakes: null,
    action: null,
    result: null,
    reflection: null,
    skills: ["ownership"],
    status: "draft",
    source: "manual",
    source_session_id: null,
    source_question_ref: null,
    notes: [],
    created_at: T,
    updated_at: T,
    ...over,
  };
}

function debrief(): Debrief {
  const base = scorecardFor("behavioral", false);
  const scorecard = {
    ...base,
    per_question: [
      { ...base.per_question[0], story_id: "st1", story_fix: "Say what you would do differently." },
      base.per_question[1],
    ],
  };
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
    scorecard,
    next_session: sessionPlan[1],
    next_custom_session: null,
    generic_mode: false,
    company_name: "Example Corp",
    company_slug: "example-corp",
    values_framework: "Example Values",
    questions: [],
    previous_signal: null,
    answers_at_bar: mockAnswersAtBar(scorecard),
  };
}

function renderDebrief(initial: Story[]) {
  setFeatureOverrides({ v2_enabled: true });
  let stories = initial;
  const saved: unknown[] = [];
  server.use(
    http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(debrief())),
    http.get("*/api/sessions/:sessionId/feedback", () => HttpResponse.json(null)),
    http.get("*/api/stories", () => HttpResponse.json(stories)),
    http.post("*/api/stories/from-answer", async ({ request }) => {
      const body = (await request.json()) as { session_id: string; question_ref: string };
      saved.push(body);
      const made = story({
        id: "st2",
        title: "Disagreement with another team",
        source: "debrief_answer",
        source_session_id: body.session_id,
        source_question_ref: body.question_ref,
      });
      stories = [made, ...stories];
      return HttpResponse.json(made, { status: 201 });
    }),
  );
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s2/debrief"]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { saved };
}

const withNote = story({ notes: [{ text: "Say what you would do differently.", session_id: "s2", question_ref: "q1", at: T }] });

describe("stories on the debrief", () => {
  it("ST-6: shows the story each answer used, linking to the workbench, and its fix sent to the story", async () => {
    renderDebrief([withNote]);
    const [first] = await screen.findAllByTestId("story-used");
    expect(await within(first).findByRole("link", { name: "Invoice cutover" })).toHaveAttribute("href", "/stories/st1");
    expect(within(first).getByText("Say what you would do differently.")).toBeInTheDocument();
    expect(within(first).getByText("Sent to story")).toBeInTheDocument();
  });

  it("ST-6: an answer with no story says No story matched", async () => {
    renderDebrief([withNote]);
    const answers = await screen.findAllByTestId("story-used");
    expect(within(answers[1]).getByText("No story matched.")).toBeInTheDocument();
  });

  it("ST-2: Save as a story makes a draft from the answer and the summary card lists it", async () => {
    const { saved } = renderDebrief([withNote]);
    const answers = await screen.findAllByTestId("story-used");
    const user = userEvent.setup();
    await user.click(await within(answers[1]).findByRole("button", { name: "Save as a story" }));

    expect(saved).toEqual([{ session_id: "s2", question_ref: "q2" }]);
    expect(await within(answers[1]).findByRole("link", { name: "Disagreement with another team" })).toHaveAttribute(
      "href",
      "/stories/st2",
    );
    expect(within(answers[1]).queryByRole("button", { name: "Save as a story" })).not.toBeInTheDocument();

    const card = await screen.findByRole("region", { name: "2 updates for your library" });
    expect(within(card).getByRole("link", { name: "Invoice cutover" })).toBeInTheDocument();
    expect(within(card).getByText("Fix note added")).toBeInTheDocument();
    expect(within(card).getByText("New draft from this debrief")).toBeInTheDocument();
  });

  it("ST-6: the summary card lists the stories this session changed", async () => {
    renderDebrief([withNote, story({ id: "st9", title: "Old story" })]);
    const card = await screen.findByRole("region", { name: "1 update for your library" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(1);
    expect(within(card).queryByText("Old story")).not.toBeInTheDocument();
  });
});
