/**
 * The v2 Home behind `v2_enabled` (FL-1), as on the canvas Home board: the coach nudge (PR-2), the
 * journeys A and B (PP-3, ST-4) and the story library.
 */
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
import { resetMockStories } from "../../mocks/storyHandlers";
import { newCoachPath } from "../coach/paths";
import type { PlanView } from "../plan/api";
import { firstGap } from "./HomeV2";
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
    // A ready interview opens its plan (the gap route redirects there with v2 on).
    expect(first.getByRole("link", { name: /Payments Reliability · Stripe/ })).toHaveAttribute("href", "/jobs/j1/gap");
    expect(screen.getByRole("link", { name: "Continue prep" })).toHaveAttribute("href", "/jobs/j1/resume");
    expect(cards[1]).toHaveTextContent("No match score yet");
    expect(cards[1]).toHaveTextContent("No interview date yet");
    // No gap analysis yet: the next step is to pick a CV.
    expect(within(cards[1]).getByRole("link", { name: "Get ready to rehearse" })).toHaveAttribute("href", "/jobs/j2/resume");
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
    // R3: the coach card and the prep card both say "Add a job description".
    expect(screen.getAllByRole("link", { name: "Add a job description" }).length).toBe(2);
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
  it("PR-2: the coach names the interview's days left and its first story gap, with Build it with me and Show my plan", async () => {
    resetMockStories();
    server.use(
      http.get("*/api/job-targets/:jobId/gap-analysis", () => HttpResponse.json({ resume_id: "r1", status: "ready" })),
      http.get("*/api/plan/:jobId/:resumeId", () => HttpResponse.json(planView("j1", "r1", 6))),
    );
    renderHome([job("j1")]);
    const coach = await screen.findByTestId("home-coach");
    expect(
      await within(coach).findByText("Your Stripe interview is in 6 days, and you don't have a learning from failure story yet. Want to build one now?"),
    ).toBeInTheDocument();
    expect(within(coach).getByRole("link", { name: "Build it with me" })).toHaveAttribute(
      "href",
      "/coach/new?skill=learning_from_failure&job=j1",
    );
    expect(within(coach).getByRole("link", { name: "Show my plan" })).toHaveAttribute("href", "/interviews/j1/r1");
    expect(within(coach).getByRole("textbox", { name: "Ask your coach" })).toBeInTheDocument();
  });

  it("ST-4: the cards sit side by side in the menu's order: resumes, interviews, then stories (with counts)", async () => {
    resetMockStories();
    renderHome([job("j1")]);
    const a = await screen.findByRole("region", { name: "Turn your career into stories that win interviews." });
    const b = screen.getByRole("region", { name: "Get ready for the interview you have." });
    const r = screen.getByRole("region", { name: "The CV your interviews are measured against." });
    expect(r.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // No journey letters.
    expect(document.body.textContent).not.toMatch(/\b[AB] · /);
    expect(await within(a).findByText("Stories")).toBeInTheDocument();
    const counts = within(a).getAllByRole("definition").map((d) => d.textContent);
    expect(counts).toEqual(["2", "1", "1"]);
    expect(within(a).getByRole("link", { name: "Open the studio" })).toHaveAttribute("href", "/stories");
  });

  it("PR-2: a typed question opens a coach session with it", () => {
    expect(newCoachPath({ ask: "Which story for leadership?", job: "j1" })).toBe(
      "/coach/new?job=j1&ask=Which+story+for+leadership%3F",
    );
  });

  it("PR-2: the first gap is a missing skill, else one only Drafts cover", () => {
    const plan = planView("j1", "r1", 6);
    expect(firstGap(plan, [{ skills: ["ownership"], status: "proven" }])).toEqual({ skill: "impact", state: "missing" });
    const all = ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"] as const;
    expect(firstGap(plan, [{ skills: [...all], status: "draft" }])).toEqual({ skill: "ownership", state: "thin" });
    expect(firstGap(plan, [{ skills: [...all], status: "proven" }])).toBeNull();
  });
});

/** The parts of the plan view Home reads (PP-1, PP-2). */
function planView(jobId: string, resumeId: string, daysLeft: number | null) {
  return {
    job: { id: jobId },
    resume: { id: resumeId },
    interview_date: daysLeft === null ? null : "2026-11-03",
    days_left: daysLeft,
    tested: [
      {
        interview_type: "behavioral",
        in_loop: true,
        competencies: ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"].map(
          (competency) => ({ competency, weight: 1, share: 0.167 }),
        ),
      },
    ],
  } as unknown as PlanView;
}
