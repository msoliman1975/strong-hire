/**
 * PP-1, PP-2, PP-4: the interview plan page with MSW. Also: with `v2_enabled` off, the gap
 * analysis, rehearsals and session setup routes still open the v1 pages; with it on, they open
 * the plan page.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { CreateSessionRequest, GapAnalysisOut, JobTargetOut, ResumeOut, Usage } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { FREE_USAGE } from "../../mocks/db";
import { gapAnalysis, jobPosting } from "../../mocks/fixtures";
import { mockStore, server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import type { PlanView } from "./api";
import { PlanPage } from "./PlanPage";

const JOB: JobTargetOut = {
  id: "j1",
  name: "Software Engineer at Acme",
  deleted: false,
  status: "extracted",
  source_url: null,
  posting: jobPosting,
  level: "senior",
  company_id: "c1",
  company_slug: "acme",
  generic_mode: false,
  stage: null,
  context: { interviewer_name: null, interviewer_role: null, recruiter_notes: null, concerns: null },
  created_at: "2026-10-01T10:00:00Z",
  archived_at: null,
};

const CV: ResumeOut = {
  id: "r1",
  name: "Ana Lopez CV",
  deleted: false,
  status: "extracted",
  has_file: true,
  resume: null,
  confirmed_at: null,
  uploaded_at: "2026-10-01T10:00:00Z",
  accepted_issues: [],
};

const GAP: GapAnalysisOut = {
  id: "g1",
  job_target_id: "j1",
  resume_id: "r1",
  resume_name: "Ana Lopez CV",
  resume_deleted: false,
  job_deleted: false,
  status: "ready",
  analysis: gapAnalysis,
  error: null,
  generic_mode: false,
  profile_version: 1,
  stale: false,
  created_at: "2026-10-02T10:00:00Z",
  updated_at: "2026-10-02T10:01:00Z",
};

const PAID: Usage = {
  ...FREE_USAGE,
  plan: "paid",
  status: "active",
  minutes_cap: 300,
  minutes_left: 300,
  free_interviews_left: 0,
  full_interviews_allowed: true,
};

function planView(over: Partial<PlanView> = {}): PlanView {
  return {
    job: JOB,
    resume: CV,
    company_mode: "curated",
    company_name: "Acme",
    values_framework: "Acme Values",
    interview_date: null,
    days_left: null,
    tested: [
      {
        interview_type: "behavioral",
        in_loop: true,
        competencies: [
          { competency: "ownership", weight: 2, share: 0.5 },
          { competency: "impact", weight: 1, share: 0.25 },
          { competency: "communication", weight: 1, share: 0.25 },
        ],
      },
      {
        interview_type: "case",
        in_loop: false,
        competencies: [{ competency: "structure", weight: 1, share: 1 }],
      },
    ],
    gap: GAP,
    reports: [
      {
        type: "interview_debrief",
        id: "s1",
        job_target_id: "j1",
        job_name: "Software Engineer at Acme",
        job_deleted: false,
        resume_id: "r1",
        resume_name: "Ana Lopez CV",
        resume_deleted: false,
        status: "ready",
        at: "2026-10-03T10:00:00Z",
        match_score: null,
        hire_signal: "Lean Hire",
        interview_type: "behavioral",
        mode: "realistic",
        duration_min: 30,
      },
    ],
    next_session: null,
    next_custom_session: null,
    setup: {
      interview_type: "hiring_manager",
      difficulty: "tough",
      mode: "coach",
      duration_min: 30,
      level: "senior",
      tone: "as_company",
    },
    ...over,
  };
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderPlan(view: PlanView, usage: Usage = PAID) {
  const bodies: CreateSessionRequest[] = [];
  const dates: (string | null)[] = [];
  let current = view;
  server.use(
    http.get("*/api/plan/:jobId/:resumeId", () => HttpResponse.json(current)),
    http.put("*/api/plan/:jobId/interview-date", async ({ request }) => {
      const { interview_date } = (await request.json()) as { interview_date: string | null };
      dates.push(interview_date);
      current = { ...current, interview_date, days_left: interview_date ? 12 : null };
      return HttpResponse.json({ interview_date, days_left: current.days_left });
    }),
    http.get("*/api/billing/usage", () => HttpResponse.json(usage)),
    http.post("*/api/sessions", async ({ request }) => {
      bodies.push((await request.json()) as CreateSessionRequest);
      return HttpResponse.json({ id: "s9" }, { status: 201 });
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/interviews/j1/r1"]}>
        <Routes>
          <Route path="/interviews/:jobId/:resumeId" element={<PlanPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, bodies, dates };
}

function signedIn(email = "ana@example.com") {
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

afterEach(() => setFeatureOverrides({}));

describe("interview plan page", () => {
  it("PP-1: shows what they'll test, where they'll probe and the earlier rehearsals", async () => {
    renderPlan(planView());
    expect(await screen.findByRole("heading", { level: 1, name: /Acme/ })).toBeInTheDocument();
    // IN-12: the CV in use links to its breakdown.
    expect(screen.getByRole("link", { name: "see its breakdown" })).toHaveAttribute("href", "/resumes/r1/check");
    const tested = screen.getByRole("region", { name: "What they'll test" });
    expect(within(tested).getByText(/Acme's interview profile and its Acme Values/)).toBeInTheDocument();
    // The rounds in their loop show; the others open on request.
    expect(within(tested).getAllByTestId("tested-type")).toHaveLength(1);
    fireEvent.click(within(tested).getByRole("button", { name: "Show the other round" }));
    const types = within(tested).getAllByTestId("tested-type");
    expect(types).toHaveLength(2);
    expect(within(types[0]).getByText("In their loop")).toBeInTheDocument();
    expect(within(types[0]).getByLabelText("Ownership: 50% of this round")).toBeInTheDocument();

    // A short summary: the top 3 areas, the match score, and the full report one click away.
    const probe = screen.getByRole("region", { name: "Where they'll probe" });
    expect(within(probe).getByTestId("probe-areas").children).toHaveLength(Math.min(3, gapAnalysis.probe_areas.length));
    expect(within(probe).getByTestId("plan-match")).toHaveTextContent(`Match ${gapAnalysis.match_score}`);
    expect(within(probe).getByRole("link", { name: "Show full report" })).toHaveAttribute(
      "href",
      expect.stringContaining("/jobs/j1/gap-report?report="),
    );
    // The practice plan moved out of this card, into "Your plan".
    expect(within(probe).queryByTestId("session-plan")).toBeNull();

    const earlier = screen.getByRole("region", { name: "Earlier rehearsals" });
    expect(within(earlier).getByText(/1 scored interview\. Latest hire signal: Lean Hire/)).toBeInTheDocument();
  });

  it("PP-1: without a gap analysis it offers to run one and cannot start a rehearsal yet", async () => {
    renderPlan(planView({ gap: null, reports: [] }));
    const probe = await screen.findByRole("region", { name: "Where they'll probe" });
    expect(within(probe).getByRole("link", { name: "Run the gap analysis" })).toHaveAttribute(
      "href",
      "/jobs/j1/context?resume=r1",
    );
    // The next rehearsal card's one primary action runs it too: never a disabled dead end.
    const next = await screen.findByRole("region", { name: "Your plan" });
    expect(await within(next).findByRole("link", { name: "Run the gap analysis" })).toHaveAttribute(
      "href",
      "/jobs/j1/context?resume=r1",
    );
    expect(screen.queryByRole("button", { name: "Start rehearsal" })).toBeNull();
  });

  it("PP-1: while the gap analysis runs, Start rehearsal waits and says why", async () => {
    renderPlan(planView({ gap: { ...planView().gap!, status: "running", analysis: null }, reports: [] }));
    // No rehearsal yet: the add flow ends on "Start your first rehearsal" (R3).
    expect(await screen.findByRole("button", { name: "Start your first rehearsal" })).toBeDisabled();
    expect(screen.getByTestId("needs-gap")).toHaveTextContent("The rehearsal unlocks when it is done");
  });

  it("PP-2: asks for the interview date, then shows the days left", async () => {
    const { user, dates } = renderPlan(planView());
    const input = await screen.findByLabelText("When is your interview?");
    await user.type(input, "2026-11-08");
    await user.click(screen.getByRole("button", { name: "Save the date" }));
    expect(await screen.findByText("12 days left")).toBeInTheDocument();
    expect(dates).toEqual(["2026-11-08"]);
    expect(screen.getByText(/Interview on Nov 8, 2026/)).toBeInTheDocument();
  });

  it("PP-2: a set date shows the countdown", async () => {
    renderPlan(planView({ interview_date: "2026-10-28", days_left: 1 }));
    expect(await screen.findByTestId("plan-countdown")).toHaveTextContent("1 day left");
    expect(screen.queryByLabelText("When is your interview?")).not.toBeInTheDocument();
  });

  it("PP-4: the setup keeps type, Custom, difficulty, tone, mode and 30 or 45 minutes", async () => {
    const { user, bodies } = renderPlan(planView());
    const setup = await screen.findByRole("form", { name: "Rehearsal setup" });
    await within(setup).findAllByText("A full interview.");
    for (const name of [/^Behavioral/, /^Hiring manager/, /^Verbal technical/, /^Case/, /^Custom/]) {
      expect(within(setup).getByRole("radio", { name })).toBeEnabled();
    }
    // Defaults from the plan: PR-2 / GA-3's type and difficulty, the company's tone, Coach.
    expect(within(setup).getByRole("radio", { name: /^Hiring manager/ })).toBeChecked();
    expect(within(setup).getByRole("radio", { name: /^Tough/ })).toBeChecked();
    expect(within(setup).getByRole("radio", { name: /^Like Acme/ })).toBeChecked();
    expect(within(setup).getByRole("radio", { name: /^Practice/ })).toBeChecked();
    expect(within(setup).getByRole("radio", { name: /^30 minutes/ })).toBeChecked();

    await user.click(within(setup).getByRole("radio", { name: /^Behavioral/ }));
    await user.click(within(setup).getByRole("radio", { name: /^Friendly/ }));
    await user.click(within(setup).getByRole("radio", { name: /^Direct/ }));
    const mode = within(setup).getByRole("group", { name: "Mode" });
    await user.click(within(mode).getByRole("radio", { name: /^Realistic/ }));
    await user.click(within(setup).getByRole("radio", { name: /^45 minutes/ }));
    await user.click(within(setup).getByRole("button", { name: "Start rehearsal" }));
    expect(await screen.findByTestId("where")).toHaveTextContent("/sessions/s9/live");
    expect(bodies[0]).toEqual({
      job_target_id: "j1",
      resume_id: "r1",
      channel: "voice",
      config: {
        interview_type: "behavioral",
        difficulty: "friendly",
        mode: "realistic",
        duration_min: 45,
        level: "senior",
        custom: null,
        tone: "direct",
      },
    });
  });

  it("RH-5: the mode labels are Realistic and Practice, with what Practice means; Practice is stored as coach", async () => {
    const { user, bodies } = renderPlan(planView());
    const setup = await screen.findByRole("form", { name: "Rehearsal setup" });
    const mode = await within(setup).findByRole("group", { name: "Mode" });
    expect(within(mode).getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["coach", "realistic"]);
    const practice = within(mode).getByRole("radio", { name: /^Practice/ });
    expect(within(mode).queryByRole("radio", { name: /^Coach/ })).toBeNull();
    expect(mode).toHaveTextContent("Pause, ask for a hint, or redo an answer. Does not count toward readiness.");
    await user.click(practice);
    await user.click(within(setup).getByRole("button", { name: "Start rehearsal" }));
    await screen.findByTestId("where");
    expect(bodies[0]?.config.mode).toBe("coach");
  });

  it("PP-4: Custom opens the shared Custom setup", async () => {
    const { user } = renderPlan(planView());
    const setup = await screen.findByRole("form", { name: "Rehearsal setup" });
    await within(setup).findAllByText("A full interview.");
    await user.click(within(setup).getByRole("radio", { name: /^Custom/ }));
    // The Custom fields replace the duration choice, as on the v1 setup page.
    expect(within(setup).queryByRole("radio", { name: /^10 minutes \(mini\)/ })).not.toBeInTheDocument();
  });

  it("PP-4, TN-3: in generic mode the tone defaults to Neutral and there is no company tone", async () => {
    renderPlan(planView({ company_mode: "generic", setup: { ...planView().setup, tone: "neutral" } }), FREE_USAGE);
    const setup = await screen.findByRole("form", { name: "Rehearsal setup" });
    expect(within(setup).getByRole("radio", { name: /^Neutral/ })).toBeChecked();
    expect(within(setup).queryByRole("radio", { name: /^Like / })).not.toBeInTheDocument();
    // Free accounts: the mini interview, as on the v1 setup page.
    expect(within(setup).getByRole("radio", { name: /^10 minutes \(mini\)/ })).toBeChecked();
  });
});

describe("v2_enabled and the old pages", () => {
  function renderApp(path: string) {
    signedIn();
    server.use(
      http.get("*/api/job-targets/:jobId", () => HttpResponse.json(JOB)),
      http.get("*/api/job-targets/:jobId/gap-analysis", () => HttpResponse.json(GAP)),
      http.get("*/api/plan/:jobId/:resumeId", () => HttpResponse.json(planView())),
    );
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("flag off: the gap analysis, rehearsals and setup routes are unchanged", async () => {
    renderApp("/jobs/j1/sessions/new?resume=r1");
    expect(await screen.findByRole("heading", { level: 1, name: "Set up your interview" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your plan" })).not.toBeInTheDocument();
  });

  it("flag off: the gap analysis page still shows", async () => {
    renderApp("/jobs/j1/gap");
    expect(await screen.findByTestId("match-score")).toBeInTheDocument();
  });

  it.each([
    ["/jobs/j1/sessions/new?resume=r1"],
    ["/jobs/j1/rehearse/r1"],
    ["/jobs/j1/gap"],
  ])("PP-1: flag on, %s opens the plan page", async (path) => {
    setFeatureOverrides({ v2_enabled: true });
    renderApp(path);
    expect(await screen.findByRole("region", { name: "Your plan" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "What they'll test" })).toBeInTheDocument();
  });
});
