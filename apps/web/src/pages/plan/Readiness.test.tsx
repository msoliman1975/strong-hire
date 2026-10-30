/** RD-1, RD-2, RD-3: practice readiness per skill, the day plan and the practice-estimate notice. */
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../App";
import { server } from "../../mocks/node";
import { DayPlan } from "./DayPlan";
import { ReadinessBadge } from "./ReadinessBadge";
import { READINESS_NOTICE, READINESS_NOTICE_SHORT, type DayPlan as DayPlanData, type DayPlanItem, type Readiness } from "./ReadinessApi";
import { ReadinessPanel, ReadinessRing } from "./ReadinessPanel";

const READINESS: Readiness = {
  job_target_id: "j1",
  kind: "practice_estimate",
  as_of: "2026-11-02",
  skills: [
    { competency: "ownership", status: "scored", score: 78, sessions_counted: 3 },
    { competency: "impact", status: "scored", score: 50, sessions_counted: 2 },
    { competency: "communication", status: "not_enough_data", score: null, sessions_counted: 1 },
  ],
};

const REHEARSAL: DayPlanItem = {
  kind: "rehearsal",
  interview_type: "behavioral",
  difficulty: "realistic",
  mode: "coach",
  focus_topics: ["Ownership"],
  competency: null,
  story_id: null,
  strength: null,
  reason: "Your lowest score is ownership.",
};

const STORY: DayPlanItem = {
  kind: "story",
  interview_type: null,
  difficulty: null,
  mode: null,
  focus_topics: [],
  competency: "conflict_handling",
  story_id: null,
  strength: "missing",
  reason: "No story shows conflict handling yet.",
};

const BASE: DayPlanData = {
  job_target_id: "j1",
  resume_id: "r1",
  interview_date: null,
  days_left: null,
  kind: "next_steps",
  days: [],
  days_not_shown: 0,
  next_steps: [],
};

function wrap(node: ReactNode) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const serve = (readiness: Readiness, plan?: DayPlanData) =>
  server.use(
    http.get("*/api/plan/:job/:resume/readiness", () => HttpResponse.json(readiness)),
    http.get("*/api/readiness/:job", () => HttpResponse.json(readiness)),
    ...(plan ? [http.get("*/api/plan/:job/:resume/day-plan", () => HttpResponse.json(plan))] : []),
  );

describe("ReadinessPanel", () => {
  it("RD-1: shows readiness per skill, with not enough data below the minimum", async () => {
    serve(READINESS);
    wrap(<ReadinessPanel jobId="j1" resumeId="r1" />);
    const rows = await screen.findAllByTestId("readiness-skill");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent(/78 · at the bar/);
    expect(rows[1]).toHaveTextContent("50");
    expect(rows[1]).not.toHaveTextContent("at the bar");
    expect(rows[2]).toHaveTextContent("Not enough data yet: 1 of 2 Realistic rehearsals");
    // The count sits next to the per-skill view.
    expect(screen.getByText("1 of 3 skills at the bar of 3 of 4.")).toBeInTheDocument();
  });

  it("RD-3: the practice-estimate notice is on the plan page's readiness view", async () => {
    serve(READINESS);
    wrap(<ReadinessPanel jobId="j1" resumeId="r1" />);
    await screen.findAllByTestId("readiness-skill");
    expect(within(screen.getByTestId("readiness-panel")).getByTestId("readiness-notice")).toHaveTextContent(
      READINESS_NOTICE,
    );
  });

  it("RD-3: the notice shows even before any readiness is scored", async () => {
    serve({ ...READINESS, skills: READINESS.skills.map((s) => ({ ...s, status: "not_enough_data", score: null })) });
    wrap(<ReadinessPanel jobId="j1" resumeId="r1" />);
    expect(await screen.findByText(/Run 2 Realistic rehearsals/)).toBeInTheDocument();
    expect(screen.getByTestId("readiness-notice")).toBeInTheDocument();
  });
});

describe("ReadinessRing and folded rows (canvas B1)", () => {
  it("RD-1, RD-3: the plan header ring shows the skills at the bar, in text, with the notice", async () => {
    serve(READINESS);
    wrap(<ReadinessRing jobId="j1" resumeId="r1" />);
    const ring = await screen.findByTestId("readiness-ring");
    expect(ring).toHaveTextContent("1 of 3 skills at the bar.");
    expect(ring).toHaveTextContent("Practice estimate, not a prediction.");
  });

  it("RD-1: no ring before any skill is scored", async () => {
    serve({ ...READINESS, skills: READINESS.skills.map((s) => ({ ...s, status: "not_enough_data", score: null })) });
    wrap(<ReadinessRing jobId="j1" resumeId="r1" />);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("readiness-ring")).toBeNull();
  });

  it("RD-1: before any skill is scored the per-skill rows fold away, one click from view", async () => {
    serve({ ...READINESS, skills: READINESS.skills.map((s) => ({ ...s, status: "not_enough_data", score: null })) });
    wrap(<ReadinessPanel jobId="j1" resumeId="r1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Show each skill (3)" }));
    expect(screen.getAllByTestId("readiness-skill")).toHaveLength(3);
  });
});

describe("ReadinessBadge", () => {
  it("RD-1 and RD-3: the Home badge counts skills at the bar, with the short notice", async () => {
    serve(READINESS);
    wrap(<ReadinessBadge jobId="j1" />);
    const badge = await screen.findByTestId("readiness-badge");
    expect(badge).toHaveTextContent("Practice readiness: 1 of 3 skills at the bar");
    expect(within(badge).getByTestId("readiness-notice")).toHaveTextContent(READINESS_NOTICE_SHORT);
  });
});

describe("DayPlan", () => {
  it("RD-2: without a date, the next three steps and a prompt to add the date", async () => {
    serve(READINESS, { ...BASE, next_steps: [REHEARSAL, STORY, { ...REHEARSAL, mode: "realistic" }] });
    wrap(<DayPlan jobId="j1" resumeId="r1" />);
    const items = await screen.findAllByTestId("day-plan-item");
    expect(screen.getByRole("heading", { name: "Your next steps" })).toBeInTheDocument();
    expect(items.map((i) => i.dataset.kind)).toEqual(["rehearsal", "story", "rehearsal"]);
    expect(items[0]).toHaveTextContent("Behavioral rehearsal");
    expect(items[0]).toHaveTextContent("Practice");
    expect(items[1]).toHaveTextContent("Build a story for");
    expect(screen.getByText(/Add your interview date/)).toBeInTheDocument();
  });

  it("RD-2: with a date, one entry per day with one or two items", async () => {
    serve(READINESS, {
      ...BASE,
      kind: "by_day",
      interview_date: "2026-11-05",
      days_left: 3,
      days: [
        { day: "2026-11-02", items: [REHEARSAL, STORY] },
        { day: "2026-11-03", items: [{ ...REHEARSAL, mode: "realistic" }] },
        { day: "2026-11-04", items: [{ ...REHEARSAL, mode: "realistic", reason: "Dress rehearsal." }] },
      ],
      days_not_shown: 2,
    });
    wrap(<DayPlan jobId="j1" resumeId="r1" />);
    expect(await screen.findByRole("heading", { name: "Your plan, day by day" })).toBeInTheDocument();
    const days = screen.getAllByTestId("day-plan-day");
    expect(days).toHaveLength(3);
    expect(within(days[0]).getAllByTestId("day-plan-item")).toHaveLength(2);
    expect(within(days[2]).getByText(/Dress rehearsal/)).toBeInTheDocument();
    expect(screen.getByText(/2 more days after these/)).toBeInTheDocument();
  });
});
