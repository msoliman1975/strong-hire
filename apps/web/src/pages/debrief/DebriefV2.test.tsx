/** The v2 debrief behind `v2_enabled` (FL-1): DB-1, DB-2, FB-2, PR-2, QB-4 and the practice notice. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { Debrief, PreviousSignal } from "../../api/types";
import { createQueryClient } from "../../App";
import { mockAnswersAtBar } from "../../mocks/debrief";
import { scorecardFor, sessionPlan } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { DebriefPage } from "../DebriefPage";
import { PRACTICE_NOTICE } from "./DebriefV2";
import { changeText } from "./StrovaVerdict";

afterEach(() => setFeatureOverrides({}));

function debrief(previous: PreviousSignal | null = null): Debrief {
  const scorecard = scorecardFor("behavioral", false);
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
    previous_signal: previous,
    answers_at_bar: mockAnswersAtBar(scorecard),
    suggestions: [],
    next_plan_item: null,
  };
}

function renderDebrief(body: Debrief, v2 = true) {
  setFeatureOverrides({ v2_enabled: v2 });
  server.use(
    http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(body)),
    http.get("*/api/sessions/:sessionId/feedback", () => HttpResponse.json(null)),
  );
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s2/debrief"]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The take's interview (U06): a Behavioral interview at Example Corp whose take 2 is this session. */
function withInterview() {
  const interview = {
    id: "iv1",
    job_target_id: "j1",
    interview_type: "behavioral",
    acting_as: { title: "Hiring Manager", company: "Example Corp", text: "Strova is acting as Hiring Manager at Example Corp" },
  };
  const readiness = { score: 58, goal: 75 };
  server.use(
    http.get("*/api/roles/:jobId/interviews", () =>
      HttpResponse.json([{ interview, readiness, takes_count: 2, last_signal: "Lean Hire" }]),
    ),
    http.get("*/api/interviews/:id", () =>
      HttpResponse.json({
        interview,
        readiness,
        takes: [
          { number: 1, session_id: "s1" },
          { number: 2, session_id: "s2" },
        ],
      }),
    ),
  );
}

const PREVIOUS: PreviousSignal = {
  session_id: "s1",
  hire_signal: "Lean No Hire",
  ended_at: "2026-10-01T10:30:00Z",
  change: 1,
};

describe("v2 debrief", () => {
  it("DB-1: shows the hire signal in its colour and the change from the previous take", async () => {
    renderDebrief(debrief(PREVIOUS));
    const signal = await screen.findByTestId("hire-signal");
    expect(signal).toHaveTextContent("Lean Hire");
    expect(signal).toHaveClass("sx-signal-lean");
    expect(screen.getByTestId("signal-change")).toHaveTextContent("Up from Lean No Hire last take");
  });

  it("DB-1: the change reads down, the same, or first take", () => {
    expect(changeText({ ...PREVIOUS, hire_signal: "Hire", change: -1, ended_at: null })).toBe("Down from Hire last take");
    expect(changeText({ ...PREVIOUS, hire_signal: "Lean Hire", change: 0, ended_at: null })).toBe("The same as last take");
    expect(changeText(null)).toBe("Your first scored take for this interview.");
  });

  it("DB-1: the first take says so", async () => {
    renderDebrief(debrief(null));
    await screen.findByTestId("hire-signal");
    expect(screen.getByTestId("signal-change")).toHaveTextContent("Your first scored take");
  });

  it("DB-3, TR-1: the header names the take, links back to the interview and to the transcript", async () => {
    withInterview();
    renderDebrief(debrief());
    expect(await screen.findByRole("heading", { level: 1, name: "Take 2 with Strova" })).toBeInTheDocument();
    expect(screen.getByText("Example Corp · Behavioral · debrief")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the interview" })).toHaveAttribute("href", "/interviews/iv1");
    expect(screen.getByRole("link", { name: "Read the transcript" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/sessions\/.+\/transcript$/),
    );
  });

  it("DB-3: the debrief opens with Strova's verdict in the interviewer hat", async () => {
    withInterview();
    renderDebrief(debrief(PREVIOUS));
    const verdict = await screen.findByRole("region", { name: "Strova's verdict" });
    expect(within(verdict).getByRole("img", { name: "Strova is interviewing" })).toHaveAttribute("width", "72");
    expect(await within(verdict).findByText("Wearing the interviewer hat: Hiring Manager at Example Corp")).toBeInTheDocument();
    expect(within(verdict).getByTestId("readiness")).toHaveTextContent("58");
    expect(within(verdict).getByTestId("hire-signal")).toBeInTheDocument();
    expect(within(verdict).getByTestId("answers-at-bar")).toBeInTheDocument();
    // The verdict comes before the answers.
    const answers = screen.getByRole("region", { name: "Answer by answer" });
    expect(verdict.compareDocumentPosition(answers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("DB-2: says how many answers met the bar", async () => {
    renderDebrief(debrief());
    // The fixture: q1 averages 3 (met), q2 averages 2 (not met).
    expect(await screen.findByTestId("answers-at-bar")).toHaveTextContent("1 of 2");
    expect(screen.getByText("Answers that met the bar")).toBeInTheDocument();
  });

  it("FB-2: each answer with its score, a quote from it, and its fix", async () => {
    renderDebrief(debrief());
    const answers = await screen.findAllByTestId("answer");
    expect(answers).toHaveLength(2);
    const first = within(answers[0]);
    expect(first.getByRole("heading", { name: "Tell me about a project you owned end to end." })).toBeInTheDocument();
    expect(first.getByText("3 of 4")).toHaveAttribute("data-met", "true");
    expect(first.getByText("“I wrote the plan and ran the cutover myself.”")).toBeInTheDocument();
    expect(answers[0]).toHaveTextContent("Fix: Did not explain the trade-offs considered");
    expect(within(answers[1]).getByText("2 of 4")).not.toHaveAttribute("data-met");
  });

  it("PR-2, QB-4: next in the plan, the Questions link, the realism rating and the practice notice", async () => {
    renderDebrief(debrief());
    const next = (await screen.findByRole("heading", { name: "Next in your plan" })).closest("section") as HTMLElement;
    expect(within(next).getByRole("link", { name: "Start this rehearsal" })).toHaveAttribute(
      "href",
      expect.stringContaining("/jobs/j1/sessions/new?type="),
    );
    expect(screen.getByRole("link", { name: "Practice questions for your weak areas" })).toHaveAttribute(
      "href",
      expect.stringContaining("company=example-corp"),
    );
    expect(await screen.findByRole("form", { name: "How real did it feel?" })).toBeInTheDocument();
    expect(screen.getByTestId("practice-notice")).toHaveTextContent(PRACTICE_NOTICE);
  });

  it("FL-1: with the flag off the debrief is the v1 page", async () => {
    renderDebrief(debrief(PREVIOUS), false);
    expect(await screen.findByRole("heading", { name: "Question by question" })).toBeInTheDocument();
    expect(screen.queryByTestId("answers-at-bar")).toBeNull();
    expect(screen.queryByTestId("signal-change")).toBeNull();
  });
});
