/** FB-1, FB-2, PR-2 and company values (IV-5) on the debrief page; CU-6, CU-8, CU-9 for Custom. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import type { Debrief } from "../api/types";
import { createQueryClient } from "../App";
import { scorecardFor, sessionPlan } from "../mocks/fixtures";
import { mockStore, server } from "../mocks/node";
import { DebriefPage } from "./DebriefPage";

function debrief(generic: boolean, duration_min: 10 | 30 | 45 = 30): Debrief {
  return {
    session: {
      id: "s1",
      job_target_id: "j1",
      config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min, level: "senior", custom: null },
      status: "completed",
      started_at: "2026-10-01T10:00:00Z",
      ended_at: "2026-10-01T10:30:00Z",
      minutes_billed: 30,
      failure_reason: null,
    },
    status: "ready",
    scorecard: scorecardFor("behavioral", generic),
    next_session: sessionPlan[1],
    generic_mode: generic,
    company_name: generic ? null : "Example Corp",
    values_framework: generic ? null : "Example Values",
    questions: [],
  };
}

function renderDebrief(body: Debrief) {
  server.use(http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(body)));
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s1/debrief"]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("debrief page", () => {
  it("a session that has not ended links back to the interview instead of waiting for a score", async () => {
    const body = debrief(true);
    renderDebrief({
      ...body,
      session: { ...body.session, status: "created", started_at: null, ended_at: null, minutes_billed: 0 },
      status: "not_ended",
      scorecard: null,
      next_session: null,
    });
    expect(await screen.findByTestId("not-ended")).toHaveTextContent("This interview has not finished");
    expect(screen.getByRole("link", { name: "Go to the interview" })).toHaveAttribute("href", "/sessions/s1/live");
    expect(screen.queryByText(/Scoring your interview/)).not.toBeInTheDocument();
  });

  it("a session that never started says so instead of 'Scoring failed'", async () => {
    const body = debrief(true);
    const reason = "We could not prepare your interviewer. Nothing was counted or billed. Start a new interview to try again.";
    renderDebrief({
      ...body,
      session: { ...body.session, status: "failed", started_at: null, ended_at: null, minutes_billed: 0, failure_reason: reason },
      status: "not_started",
      scorecard: null,
      next_session: null,
    });
    expect(await screen.findByTestId("not-started")).toHaveTextContent(reason);
    expect(screen.getByRole("link", { name: "Set up another session" })).toBeInTheDocument();
    expect(screen.queryByText(/Scoring failed/)).not.toBeInTheDocument();
  });

  it("a mini interview says how many questions the signal is based on", async () => {
    const body = debrief(true, 10);
    renderDebrief(body);
    const note = await screen.findByTestId("mini-note");
    const count = body.scorecard?.per_question.length ?? 0;
    expect(note).toHaveTextContent(`Based on ${count} questions. Practice signal only.`);
    expect(note).toHaveTextContent("not counted in your progress trends");
  });

  it("a full interview has no mini note", async () => {
    renderDebrief(debrief(true, 30));
    expect(await screen.findByTestId("hire-signal")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-note")).not.toBeInTheDocument();
  });

  it("shows the hire signal, rationale, per-question rubric and next session (FB-1, FB-2, PR-2)", async () => {
    renderDebrief(debrief(true));
    expect(await screen.findByTestId("hire-signal")).toHaveTextContent("Lean Hire");
    expect(screen.getByText(/clear ownership of the invoice migration/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Question by question" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Next rehearsal" })).toBeInTheDocument();
  });

  it("FB-1: an earned verdict (Hire) shows the green check; Lean Hire does not", async () => {
    const body = debrief(true);
    const hire = { ...body, scorecard: { ...body.scorecard!, hire_signal: "Hire" as const } };
    const { unmount } = renderDebrief(hire);
    expect(await screen.findByTestId("hire-signal")).toHaveTextContent("Hire");
    expect(document.querySelector(".verdict .check-badge")).not.toBeNull();
    unmount();

    renderDebrief(debrief(true));
    expect(await screen.findByTestId("hire-signal")).toHaveTextContent("Lean Hire");
    expect(document.querySelector(".verdict .check-badge")).toBeNull();
  });

  it("company mode shows the company values with scores and quotes", async () => {
    renderDebrief(debrief(false));
    const section = (await screen.findByRole("heading", { name: "Example Values" })).closest("section");
    expect(section).not.toBeNull();
    const table = within(section as HTMLElement);
    expect(table.getByText("Users first")).toBeInTheDocument();
    expect(table.getByText("“Merchants were waiting four hours for invoices.”")).toBeInTheDocument();
    expect(screen.getAllByText("(company value)").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("values-generic")).toBeNull();
  });

  it("generic mode says that company values are not scored", async () => {
    renderDebrief(debrief(true));
    expect(await screen.findByTestId("values-generic")).toHaveTextContent(
      "general interview style, with no company profile. Company values are not scored.",
    );
    expect(screen.queryByText("(company value)")).toBeNull();
  });
});

/** CU-6, CU-8, CU-9: a Custom session's debrief. */
function customDebrief(): Debrief {
  const base = debrief(true);
  const card = scorecardFor("behavioral", true);
  return {
    ...base,
    session: {
      ...base.session,
      config: {
        ...base.session.config,
        interview_type: "custom",
        custom: {
          categories: [
            { category: "technical_qa", share: 0.5, focus: ["Idempotency"] },
            { category: "behavioral", share: 0.5, focus: [] },
          ],
          questions: [
            {
              text: "How would you make a payment API safe to retry?",
              category: "technical_qa",
              competencies: ["technical_depth"],
              must_ask: true,
              verbatim: false,
              saved_question_id: null,
            },
            {
              text: "Tell me about a project you owned end to end.",
              category: "behavioral",
              competencies: ["ownership"],
              must_ask: true,
              verbatim: true,
              saved_question_id: "sq-already",
            },
          ],
        },
      },
    },
    scorecard: {
      ...card,
      per_question: [
        ...card.per_question,
        {
          question_ref: "own-1",
          question_text: "How would you make a payment API safe to retry?",
          scores: [{ competency: "technical_depth", score: 3, justification: "Correct approach.", quotes: ["Use a key."] }],
          value_scores: [],
          strengths: ["Correct use of idempotency keys"],
          misses: [],
        },
      ],
    },
    questions: [
      { question_ref: "own-1", text: "How would you make a payment API safe to retry?", source: "candidate", category: "technical_qa", must_ask: true, verbatim: false },
      { question_ref: "q1", text: "Tell me about a project you owned end to end.", source: "planner", category: "behavioral", must_ask: false, verbatim: false },
      { question_ref: "q2", text: "Tell me about a time you disagreed with another team.", source: "planner", category: "behavioral", must_ask: false, verbatim: false },
    ],
  };
}

function SetupProbe() {
  const location = useLocation();
  const state = location.state as { setup?: { config: { interview_type: string } } } | null;
  return <p data-testid="setup-probe">{`${location.pathname}${location.search} ${state?.setup?.config.interview_type ?? "none"}`}</p>;
}

function renderCustomDebrief(body: Debrief) {
  const repeats: string[] = [];
  server.use(
    http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(body)),
    http.post("*/api/sessions/:sessionId/repeat", ({ params }) => {
      repeats.push(String(params.sessionId));
      return HttpResponse.json({ job_target_id: "j1", resume_id: "r1", config: body.session.config, channel: "voice" });
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/sessions/s1/debrief"]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
          <Route path="/jobs/:jobId/sessions/new" element={<SetupProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, repeats };
}

describe("Custom debrief", () => {
  it("CU-6: groups the questions by kind in the candidate's order and marks own questions", async () => {
    renderCustomDebrief(customDebrief());
    await screen.findByTestId("hire-signal");
    const groups = screen.getAllByRole("heading", { level: 3 }).filter((h) => h.className === "question-group__title");
    expect(groups.map((g) => g.textContent)).toEqual(["Verbal technical Q&A", "Behavioral"]);
    const technical = within(screen.getByTestId("group-technical_qa"));
    expect(technical.getByText("Your question")).toBeInTheDocument();
    expect(technical.getByRole("heading", { name: /How would you make a payment API safe to retry\?/ })).toBeInTheDocument();
    const behavioral = within(screen.getByTestId("group-behavioral"));
    expect(behavioral.getAllByRole("listitem").filter((li) => li.classList.contains("question-card"))).toHaveLength(2);
    expect(behavioral.queryByText("Your question")).not.toBeInTheDocument();
  });

  it("a standard debrief has no groups and no Custom buttons", async () => {
    renderDebrief(debrief(true));
    await screen.findByTestId("hire-signal");
    expect(screen.queryByTestId("group-behavioral")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run this setup again" })).not.toBeInTheDocument();
  });

  it("CU-9: 'Run this setup again' opens the setup prefilled", async () => {
    const { user, repeats } = renderCustomDebrief(customDebrief());
    await user.click(await screen.findByRole("button", { name: "Run this setup again" }));
    expect(await screen.findByTestId("setup-probe")).toHaveTextContent("/jobs/j1/sessions/new?resume=r1 custom");
    expect(repeats).toEqual(["s1"]);
  });

  it("CU-8: 'Save my questions' saves the own questions that are not saved yet", async () => {
    const { user } = renderCustomDebrief(customDebrief());
    await user.click(await screen.findByRole("button", { name: "Save my questions" }));
    expect(await screen.findByTestId("saved-result")).toHaveTextContent("Saved 1 question to My questions.");
    expect(mockStore.db.savedQuestions.map((q) => q.text)).toEqual(["How would you make a payment API safe to retry?"]);
    expect(screen.getByRole("button", { name: "Save my questions" })).toBeDisabled();
  });
});
