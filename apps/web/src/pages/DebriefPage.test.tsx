/** FB-1, FB-2, PR-2 and company values (IV-5) on the debrief page. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import type { Debrief } from "../api/types";
import { createQueryClient } from "../App";
import { scorecardFor, sessionPlan } from "../mocks/fixtures";
import { server } from "../mocks/node";
import { DebriefPage } from "./DebriefPage";

function debrief(generic: boolean, duration_min: 10 | 30 | 45 = 30): Debrief {
  return {
    session: {
      id: "s1",
      job_target_id: "j1",
      config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min, level: "senior" },
      status: "completed",
      started_at: "2026-10-01T10:00:00Z",
      ended_at: "2026-10-01T10:30:00Z",
      minutes_billed: 30,
    },
    status: "ready",
    scorecard: scorecardFor("behavioral", generic),
    next_session: sessionPlan[1],
    generic_mode: generic,
    company_name: generic ? null : "Example Corp",
    values_framework: generic ? null : "Example Values",
  };
}

function renderDebrief(body: Debrief) {
  server.use(http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(body)));
  render(
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
    expect(screen.getByRole("heading", { name: "Next session" })).toBeInTheDocument();
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
