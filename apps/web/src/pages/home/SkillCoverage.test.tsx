/**
 * ST-4: Home shows the story library and the map of the skills the stories cover, with gaps
 * marked. The skills come from the plan pages of the user's interviews (MSW).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { JobTargetSummary } from "../../api/types";
import { createQueryClient } from "../../App";
import { jobPosting } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import type { PlanView } from "../plan/api";
import { DashboardPage } from "../DashboardPage";
import { coverageOf, interviewSkills, planSkills } from "./SkillCoverage";

type Tested = Pick<PlanView, "tested">;

const weights = (comps: string[]) => comps.map((competency) => ({ competency, weight: 1, share: 0.5 }));

const CURATED = {
  tested: [
    { interview_type: "behavioral", in_loop: true, competencies: weights(["ownership", "conflict_handling"]) },
    { interview_type: "hiring_manager", in_loop: true, competencies: weights(["judgment"]) },
    { interview_type: "case", in_loop: false, competencies: weights(["structure"]) },
  ],
} as unknown as Tested;

const GENERIC = {
  tested: [
    { interview_type: "technical_qa", in_loop: false, competencies: weights(["accuracy"]) },
    { interview_type: "behavioral", in_loop: false, competencies: weights(["impact", "ownership"]) },
  ],
} as unknown as Tested;

const STORIES = [
  mockStory({ id: "s1", title: "Checkout migration", skills: ["ownership"], status: "proven", action: "I led it." }),
  mockStory({ id: "s2", title: "Pushback from platform", skills: ["conflict_handling", "ownership"] }),
];

describe("coverage rules", () => {
  it("ST-4: a plan tests the rounds in the loop; a generic plan, the behavioral round", () => {
    expect(planSkills(CURATED)).toEqual(["ownership", "conflict_handling", "judgment"]);
    expect(planSkills(GENERIC)).toEqual(["impact", "ownership"]);
  });

  it("ST-4: the skills are the union of the plans' skills; no plans gives the behavioral skills", () => {
    expect(interviewSkills([CURATED, GENERIC])).toEqual(["ownership", "conflict_handling", "judgment", "impact"]);
    expect(interviewSkills([])).toContain("learning_from_failure");
  });

  it("ST-4: covered by a Proven story, thin with only Drafts, missing with none", () => {
    expect(coverageOf("ownership", STORIES)).toBe("covered");
    expect(coverageOf("conflict_handling", STORIES)).toBe("thin");
    expect(coverageOf("judgment", STORIES)).toBe("missing");
  });
});

function summary(id: string): JobTargetSummary {
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
    },
    match_score: 72,
    gap_status: "ready",
    sessions_count: 0,
    last_session_at: null,
    in_use: true,
  } as unknown as JobTargetSummary;
}

function renderHome(jobs: JobTargetSummary[]) {
  server.use(
    http.get("*/api/job-targets", () => HttpResponse.json(jobs)),
    http.get("*/api/job-targets/:jobId/progress", () => HttpResponse.json({ detail: "none" }, { status: 404 })),
    http.get("*/api/job-targets/:jobId/gap-analysis", ({ params }) =>
      HttpResponse.json({ id: `g-${String(params.jobId)}`, job_target_id: params.jobId, resume_id: "r1" }),
    ),
    http.get("*/api/plan/:jobId/:resumeId", () => HttpResponse.json(CURATED)),
  );
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  resetMockStories(STORIES);
});
afterEach(() => setFeatureOverrides({}));

describe("Home story sections", () => {
  it("ST-4: Home shows the story library with counts and the newest stories", async () => {
    renderHome([summary("j1")]);
    const library = await screen.findByRole("region", { name: "Your story library" });
    // The counts sit on the journey A card, as on the canvas.
    const journey = screen.getByRole("region", { name: "Turn your career into stories that win interviews." });
    const count = (label: string) => within(journey).getAllByText(label).find((el) => el.tagName === "DT")?.nextSibling;
    expect(count("Stories")).toHaveTextContent("2");
    expect(count("Proven")).toHaveTextContent("1");
    expect(count("Need work")).toHaveTextContent("1");
    expect(within(library).getAllByTestId("home-story")).toHaveLength(2);
    expect(within(library).getByRole("link", { name: "All 2 stories" })).toHaveAttribute("href", "/stories");
    expect(within(library).getByRole("link", { name: "Checkout migration" })).toHaveAttribute("href", "/stories/s1");
  });

  it("ST-4: the coverage map marks each interview skill covered, thin or missing, in text", async () => {
    renderHome([summary("j1")]);
    const map = await screen.findByRole("region", { name: "What your stories prove" });
    const skills = await within(map).findAllByTestId("skill-coverage");
    expect(skills.map((s) => [s.textContent, s.dataset.coverage])).toEqual([
      ["Ownership Covered", "covered"],
      ["Conflict handling Thin", "thin"],
      ["Judgment Missing. Build a story for it with the coach", "missing"],
    ]);
    expect(within(skills[2]).getByRole("link")).toHaveAttribute("href", "/coach/new?skill=judgment");
    expect(within(skills[0]).queryByRole("link")).toBeNull();
  });

  it("ST-4: with no interviews, the map uses the behavioral skills", async () => {
    renderHome([]);
    const map = await screen.findByRole("region", { name: "What your stories prove" });
    expect(map).toHaveTextContent("Across the skills behavioral interviews test");
    expect(within(map).getAllByTestId("skill-coverage")).toHaveLength(6);
  });

  it("ST-4: an empty library says how to start", async () => {
    resetMockStories([]);
    renderHome([]);
    const library = await screen.findByRole("region", { name: "Your story library" });
    expect(library).toHaveTextContent("Save an answer from a debrief");
    expect(within(library).getByRole("link", { name: "Write one yourself" })).toHaveAttribute("href", "/stories/new");
    expect(within(library).getByRole("link", { name: "Build a story" })).toHaveAttribute("href", "/coach/new");
  });
});
