/** The v2 Home behind `v2_enabled` (FL-1): interview cards (PP-3) and the coach's PR-2 advice. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { JobTargetSummary } from "../../api/types";
import { createQueryClient } from "../../App";
import { jobPosting, sessionPlan } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { DashboardPage } from "../DashboardPage";
import { coachAdvice, daysUntil, focusInterview } from "./interviews";

afterEach(() => setFeatureOverrides({}));

const TODAY = new Date(2026, 9, 27);

function job(id: string, changes: Record<string, unknown> = {}, interviewDate: string | null = null): JobTargetSummary {
  return {
    job_target: {
      id,
      name: null,
      deleted: false,
      status: "extracted",
      source_url: null,
      posting: jobPosting,
      level: "senior",
      company_id: null,
      company_slug: null,
      generic_mode: false,
      stage: null,
      context: null,
      created_at: "2026-10-01T10:00:00Z",
      // S10 adds interview_date to the job API; Home reads it when it is there.
      ...(interviewDate ? { interview_date: interviewDate } : {}),
    },
    match_score: 72,
    gap_status: "ready",
    sessions_count: 2,
    last_session_at: "2026-10-20T10:00:00Z",
    in_use: true,
    ...changes,
  } as unknown as JobTargetSummary;
}

function renderHome(jobs: JobTargetSummary[], v2 = true) {
  setFeatureOverrides({ v2_enabled: v2 });
  server.use(
    http.get("*/api/job-targets", () => HttpResponse.json(jobs)),
    http.get("*/api/job-targets/:jobId/progress", () =>
      HttpResponse.json({
        job_target_id: "j1",
        snapshots: [],
        trends: [],
        next_session: sessionPlan[0],
        next_custom_session: null,
        own_question_points: [],
      }),
    ),
  );
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("v2 Home", () => {
  it("PP-3: one card per interview with company, role, match score and days left", async () => {
    renderHome([job("j1", {}, "2026-11-02"), job("j2", { match_score: null, gap_status: null }, null)]);
    const cards = await screen.findAllByTestId("interview-card");
    expect(cards).toHaveLength(2);
    const first = within(cards[0]);
    expect(first.getByRole("heading")).toHaveTextContent("Senior Software Engineer, Payments Reliability · Stripe");
    expect(cards[0]).toHaveTextContent("Match 72/100");
    expect(first.getByText(/days left|Today|Interview passed/)).toBeInTheDocument();
    expect(first.getByRole("link", { name: "Continue prep" })).toHaveAttribute("href", "/jobs/j1/resume");
    expect(cards[1]).toHaveTextContent("No match score yet");
    expect(cards[1]).toHaveTextContent("No interview date yet");
    expect(within(cards[1]).getByRole("link", { name: "Get ready to rehearse" })).toHaveAttribute("href", "/jobs/j2/gap");
  });

  it("PR-2: the coach gives the next-session advice as one sentence", async () => {
    renderHome([job("j1")]);
    const coach = await screen.findByTestId("home-coach");
    expect(await within(coach).findByText(/^For Stripe: practice Behavioral at Realistic difficulty next/)).toBeInTheDocument();
    expect(within(coach).getByRole("link", { name: "Start the next rehearsal" })).toHaveAttribute("href", "/jobs/j1/resume");
  });

  it("PP-3: an empty Home asks for the first interview", async () => {
    renderHome([]);
    expect(await screen.findByText(/Add the job you are interviewing for/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Add (your|an) interview/ }).length).toBe(2);
  });

  it("FL-1: with the flag off Home is the v1 dashboard", async () => {
    renderHome([job("j1")], false);
    expect(await screen.findByRole("heading", { name: "Interview rehearsals" })).toBeInTheDocument();
    expect(screen.queryByTestId("interview-card")).toBeNull();
  });

  it("PP-3: days left count whole days in the browser's time zone", () => {
    expect(daysUntil("2026-11-02", TODAY)).toBe(6);
    expect(daysUntil("2026-10-27", TODAY)).toBe(0);
    expect(daysUntil("2026-10-26", TODAY)).toBe(-1);
  });

  it("PR-2: the coach talks about the soonest interview ahead, with its days left", () => {
    const later = job("j1", {}, "2026-11-20");
    const sooner = job("j2", {}, "2026-11-02");
    const passed = job("j3", {}, "2026-10-01");
    expect(focusInterview([later, passed, sooner], TODAY)?.job_target.id).toBe("j2");
    expect(coachAdvice(sooner, sessionPlan[0], TODAY)).toBe(
      "Your Stripe interview is in 6 days: practice Behavioral at Realistic difficulty next, on Leading without authority and Cross-team design reviews.",
    );
    expect(coachAdvice(job("j4", { match_score: null }), null, TODAY)).toBe(
      "Finish setting up Stripe, and I will plan your first rehearsal.",
    );
    expect(coachAdvice(null, null, TODAY)).toMatch(/^Add the job you are interviewing for/);
  });
});
