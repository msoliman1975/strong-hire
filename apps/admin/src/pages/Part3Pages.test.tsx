/** v2 Part 3 (S38): Coach and Readiness pages, and the brief and rubric panel (AD-5). */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw/http";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import type { Part3Coach } from "../api/part3";
import { SessionSetupPanel } from "../components/SessionSetupPanel";
import { API, mockSignIn } from "../mocks/handlers";
import { mockStore, server } from "../mocks/node";
import { MOCK_PART3_COACH } from "../mocks/part3Handlers";

function renderAt(path: string) {
  mockStore.db.users["admin@example.com"] = {
    id: "00000000-0000-4000-8000-0000000000a9",
    org_id: "00000000-0000-4000-8000-0000000000b9",
    email: "admin@example.com",
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: null,
    profile_complete: true,
  };
  mockSignIn(mockStore, "admin@example.com");
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Coach (AD-5)", () => {
  it("AD-5: shows coach sessions, cost per session, minutes against caps, by week", async () => {
    renderAt("/coach");
    expect(await screen.findByRole("heading", { name: "Coach", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Cost per coach session")).toBeInTheDocument();
    expect(screen.getByText("$0.04")).toBeInTheDocument();
    expect(screen.getByText("Coach minutes as a share of plan caps").nextElementSibling).toHaveTextContent("12.0%");
    expect(screen.getByText("Would pass the cap if coach minutes counted").nextElementSibling).toHaveTextContent("1");
    const rows = within(screen.getByRole("table", { name: "Coach sessions by week" })).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("2026-10-26");
    expect(rows[0]).toHaveTextContent("67");
    expect(within(screen.getByRole("navigation", { name: "Admin" })).getByRole("link", { name: "Coach" })).toHaveAttribute(
      "href",
      "/coach",
    );
  });

  it("AD-5: says there is no coach eval run yet", async () => {
    renderAt("/coach");
    expect(await screen.findByText(/No coach eval run yet/)).toBeInTheDocument();
  });

  it("AD-5: shows the latest coach eval results", async () => {
    const run = {
      file: "coach-hosted-20301010.json",
      suite: "coach",
      profile: "hosted",
      started_at: "2030-10-10T10:00:00Z",
      git_sha: "abcdef1234",
      dev_data: false,
      passed: true,
      metrics: [
        { key: "coach_invented_facts", name: "Invented facts", value: 0, threshold: "= 0", passed: true },
        { key: "coach_judge_pass", name: "Judge pass rate", value: 0.95, threshold: ">= 0.9", passed: true },
      ],
    };
    const body: Part3Coach = { ...MOCK_PART3_COACH, evals: { latest: run, runs: [run], reason: null } };
    server.use(http.get(`${API}/admin/part3/coach`, () => HttpResponse.json(body)));
    renderAt("/coach");
    const table = await screen.findByRole("table", { name: "Coach eval metrics" });
    expect(within(table).getByText("Invented facts").closest("tr")).toHaveTextContent("Pass");
    expect(screen.getByText(/on the/)).toHaveTextContent("hosted");
  });
});

describe("Readiness (AD-5, RD-3)", () => {
  it("AD-5: readiness by skill, labeled a practice estimate", async () => {
    renderAt("/readiness");
    expect(await screen.findByRole("heading", { name: "Readiness", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Practice estimate.")).toBeInTheDocument();
    const rows = within(screen.getByRole("table", { name: "Readiness by skill" })).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Ownership");
    expect(rows[0]).toHaveTextContent("3.10");
    expect(rows[2]).toHaveTextContent("Not enough data");
  });
});

describe("Brief and rubric (AD-5, RS-2)", () => {
  it("AD-5: shows a recruiter screen's brief questions and the rubric used", () => {
    render(
      <SessionSetupPanel
        setup={{
          brief: {
            session: { interview_type: "recruiter_screen" },
            target_competencies: ["motivation", "logistics_and_expectations"],
            questions: [
              { id: "q2", text: "When could you start?", competencies: ["logistics_and_expectations"], priority: 2 },
              { id: "q1", text: "Why this role?", competencies: ["motivation"], priority: 1 },
            ],
            persona: { tone: "warm", pushback_style: "light", closing_style: "next steps" },
          },
          rubric: { ref: "scorer/rubric_recruiter_screen.v1", text: "Score motivation 1 to 4.", scored: true },
        }}
      />,
    );
    expect(screen.getByText("Motivation, Logistics and expectations")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Brief questions" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Why this role?");
    expect(screen.getByText("scorer/rubric_recruiter_screen.v1")).toBeInTheDocument();
    expect(screen.getByText("Score motivation 1 to 4.")).toBeInTheDocument();
  });

  it("AD-5: without consent there is no brief, only the rubric", () => {
    render(
      <SessionSetupPanel
        setup={{ brief: null, rubric: { ref: "scorer/rubric.v2", text: null, scored: false } }}
      />,
    );
    expect(screen.getByText(/No brief to show/)).toBeInTheDocument();
    expect(screen.getByText(/not scored yet/)).toBeInTheDocument();
  });
});
