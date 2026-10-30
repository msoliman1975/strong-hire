/**
 * ST-4: the coverage rules (covered, thin, missing) for the skills the interviews test. Home's
 * story summary and the coverage map on Career Stories are tested in HomeStrova.test.tsx and
 * StoriesPage.test.tsx.
 */
import { describe, expect, it } from "vitest";

import { mockStory } from "../../mocks/storyHandlers";
import type { PlanView } from "../plan/api";
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
