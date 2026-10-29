/** IN-12: the rule-based CV check. Pure, deterministic, no model calls. */
import { describe, expect, it } from "vitest";

import type { Resume } from "../../api/types";
import {
  checkResume,
  fitKey,
  formatSpan,
  groupSkills,
  newestFirst,
  roleIds,
  spanLength,
  type ResumeIssue,
} from "./resumeChecks";

type Role = Resume["roles"][number];

const TODAY = "2026-10";

function role(over: Partial<Role>): Role {
  return {
    title: "Product Manager",
    company: "Acme",
    start: "2020-01",
    end: "2021-12",
    achievements: ["Cut checkout errors 40% across three teams", "Led a team of 4 engineers to launch payouts"],
    skills: [],
    ...over,
  };
}

function cv(roles: Role[], over: Partial<Resume> = {}): Resume {
  return {
    summary: "Product manager with 8 years in payments. I led cross-team launches for 12,000 merchants.",
    roles,
    skills: [],
    education: [],
    certifications: [],
    ...over,
  };
}

const keys = (issues: ResumeIssue[]) => issues.map((i) => i.key);
const find = (issues: ResumeIssue[], prefix: string) => issues.find((i) => i.key.startsWith(prefix));

describe("IN-12 dates", () => {
  it("IN-12: a clean CV has no issues", () => {
    const issues = checkResume(
      cv([role({ company: "Lumen", start: "2022-03", end: null }), role({ company: "Northwind", start: "2019-06", end: "2022-02" })]),
      { today: TODAY },
    );
    expect(issues).toEqual([]);
  });

  it("IN-12: finds a gap over 3 months, with the period", () => {
    const issues = checkResume(
      cv([role({ company: "Lumen", start: "2022-03", end: null }), role({ company: "Northwind", start: "2019-06", end: "2021-08" })]),
      { today: TODAY },
    );
    const gap = find(issues, "dates.gap:");
    expect(gap?.title).toBe("A 6-month gap");
    expect(gap?.gap).toEqual({ from: "Aug 2021", to: "Mar 2022" });
    expect(gap?.key).toBe("dates.gap:northwind/product-manager>lumen/product-manager");
  });

  it("IN-12: does not report a gap of 3 months or a gap another role covers", () => {
    const issues = checkResume(
      cv([
        role({ company: "A", start: "2022-01", end: null }),
        role({ company: "B", start: "2018-01", end: "2021-09" }),
        role({ company: "C", start: "2015-01", end: "2018-06", title: "Analyst" }),
      ]),
      { today: TODAY },
    );
    // B to A is 3 months (Oct, Nov, Dec); C overlaps B, so nothing between them.
    expect(find(issues, "dates.gap:")).toBeUndefined();
  });

  it("IN-12: finds overlapping roles and ignores a one-month handover", () => {
    const issues = checkResume(
      cv([role({ company: "Lumen Pay", start: "2022-03", end: null }), role({ company: "Northwind", start: "2019-06", end: "2022-06" })]),
      { today: TODAY },
    );
    const overlap = find(issues, "dates.overlap:");
    expect(overlap?.detail).toBe("Northwind ends Jun 2022, Lumen Pay starts Mar 2022");
    expect(overlap?.fieldNote).toBe("Overlaps Lumen Pay by 3 months");
    expect(overlap?.target).toEqual({ section: "role", role: 1, field: "end" });

    const handover = checkResume(
      cv([role({ company: "Lumen", start: "2022-03", end: null }), role({ company: "Northwind", start: "2019-06", end: "2022-03" })]),
      { today: TODAY },
    );
    expect(find(handover, "dates.overlap:")).toBeUndefined();
  });

  it("IN-12: finds an end before the start and future dates", () => {
    const issues = checkResume(
      cv([role({ company: "Lumen", start: "2027-01", end: null }), role({ company: "Northwind", start: "2021-06", end: "2020-01" })]),
      { today: TODAY },
    );
    expect(keys(issues)).toContain("dates.end-before-start:northwind/product-manager");
    expect(keys(issues)).toContain("dates.future:lumen/product-manager:start");
  });

  it("IN-12: finds years without months, read in the user's favor for gaps", () => {
    const issues = checkResume(
      cv([role({ company: "Brightline", start: "2017-01", end: null }), role({ company: "Kestrel Bank", start: "2014", end: "2016" })]),
      { today: TODAY },
    );
    expect(find(issues, "dates.year-only:")?.title).toBe("Years only on Kestrel Bank");
    expect(find(issues, "dates.gap:")).toBeUndefined();
  });

  it("IN-12: asks about a current role not marked", () => {
    const issues = checkResume(cv([role({ company: "Lumen", start: "2022-03", end: "2026-10" })]), { today: TODAY });
    expect(find(issues, "dates.current-not-marked:")?.title).toBe("Is Lumen your current role?");
    const old = checkResume(cv([role({ company: "Lumen", start: "2022-03", end: "2025-10" })]), { today: TODAY });
    expect(find(old, "dates.current-not-marked:")).toBeUndefined();
  });

  it("IN-12: reports two current roles as an overlap", () => {
    const issues = checkResume(
      cv([role({ company: "A", start: "2024-01", end: null }), role({ company: "B", start: "2025-01", end: null })]),
      { today: TODAY },
    );
    expect(find(issues, "dates.overlap:")?.title).toBe("Two current roles");
  });
});

describe("IN-12 detail", () => {
  it("IN-12: finds roles with fewer than 2 achievements and achievements without a result", () => {
    const issues = checkResume(
      cv([
        role({
          company: "Northwind",
          end: null,
          achievements: ["Owned the onboarding flow for small businesses.", "Cut onboarding time by 30%."],
        }),
        role({ company: "Brightline", start: "2018-01", end: "2019-12", achievements: ["Grew activation 12%"] }),
      ]),
      { today: TODAY },
    );
    const noResult = find(issues, "detail.no-result:");
    expect(noResult?.items).toEqual([0]);
    expect(noResult?.target).toEqual({ section: "role", role: 0, field: "achievement", item: 0 });
    expect(find(issues, "detail.few-achievements:")?.key).toBe("detail.few-achievements:brightline/product-manager");
  });

  it("IN-12: advice for an achievement without a result offers proxy and qualitative wording, not only numbers", () => {
    const issues = checkResume(cv([role({ end: null, achievements: ["Ran usability tests for the app", "Owned research"] })]), {
      today: TODAY,
    });
    const noResult = find(issues, "detail.no-result:")!;
    expect(noResult.why).toContain("you do not need one");
    expect(noResult.why).toContain("improved task success, time on task and error rate in usability benchmarks");
    expect(noResult.why).toMatch(/scale and scope/);
    expect(noResult.fieldNote).not.toMatch(/number/i);
  });

  it('IN-12: finds "we" with no "I"', () => {
    const issues = checkResume(
      cv([role({ end: null, achievements: ["We shipped a new checkout, 20% faster", "Our team grew revenue 10%"] })]),
      { today: TODAY },
    );
    expect(find(issues, "detail.we-no-i:")?.items).toEqual([0, 1]);
    const withI = checkResume(
      cv([role({ end: null, achievements: ["We shipped a new checkout, 20% faster", "I led the rollout to 3 markets"] })]),
      { today: TODAY },
    );
    expect(find(withI, "detail.we-no-i:")).toBeUndefined();
  });

  it("IN-12: finds a missing, very short or number-free summary", () => {
    const one = [role({ end: null })];
    expect(keys(checkResume(cv(one, { summary: null }), { today: TODAY }))).toContain("detail.summary-missing");
    expect(keys(checkResume(cv(one, { summary: "PM." }), { today: TODAY }))).toContain("detail.summary-short");
    expect(
      keys(
        checkResume(
          cv(one, { summary: "Product manager in payments and marketplaces who leads launches and turns messy problems into roadmaps." }),
          { today: TODAY },
        ),
      ),
    ).toContain("detail.summary-no-number");
  });
});

describe("IN-12 level, consistency and the job", () => {
  const plain = ["Wrote the onboarding guide, 30% fewer tickets", "Shipped search filters used by 2,000 users"];

  it("IN-12: a Senior target with no scope signals", () => {
    const resume = cv([role({ end: null, achievements: plain })], { summary: "Engineer with 6 years in search. 2 patents." });
    expect(keys(checkResume(resume, { today: TODAY, job: { level: "senior", level_label: "Senior", must_have_skills: [], title: "Senior PM" } }))).toContain(
      "level.no-scope",
    );
    expect(keys(checkResume(resume, { today: TODAY, job: { level: "mid", level_label: null, must_have_skills: [], title: "PM" } }))).not.toContain(
      "level.no-scope",
    );
    // No job: the newest title sets the level.
    const senior = cv([role({ title: "Senior Engineer", end: null, achievements: plain })], resume);
    expect(keys(checkResume({ ...senior, roles: [role({ title: "Senior Engineer", end: null, achievements: plain })] }, { today: TODAY }))).toContain(
      "level.no-scope",
    );
  });

  it("IN-12: skills used in roles but not in Skills, and the same company twice", () => {
    const issues = checkResume(
      cv(
        [
          role({ company: "Acme Inc.", title: "Senior PM", start: "2022-01", end: null, skills: ["SQL", "Figma"] }),
          role({ company: "ACME", title: "PM", start: "2019-01", end: "2021-12", skills: ["sql"] }),
        ],
        { skills: ["Figma"] },
      ),
      { today: TODAY },
    );
    expect(find(issues, "consistency.skills-missing:")?.detail).toBe("SQL");
    expect(find(issues, "consistency.same-company:")?.roles).toEqual([0, 1]);
  });

  it("IN-12: the job's must-have skills that never appear in the CV", () => {
    const issues = checkResume(cv([role({ end: null, skills: ["Go"] })], { skills: ["Kafka"] }), {
      today: TODAY,
      job: { level: null, level_label: null, title: "Engineer", must_have_skills: ["Go", "Kafka", "Kubernetes", "payments"] },
    });
    expect(find(issues, "job.must-have:")?.detail).toBe("Kubernetes");
    expect(checkResume(cv([role({ end: null })]), { today: TODAY }).some((i) => i.group === "job")).toBe(false);
  });
});

describe("IN-12 stable keys", () => {
  it("IN-12: keys survive reordering roles and edits to other roles", () => {
    const a = role({ company: "Lumen", start: "2022-03", end: null, achievements: ["Owned onboarding"] });
    const b = role({ company: "Northwind", start: "2019-06", end: "2021-08" });
    const before = keys(checkResume(cv([a, b]), { today: TODAY }));
    const after = keys(
      checkResume(cv([{ ...b, achievements: [...b.achievements, "Hired 3 PMs"] }, a]), { today: TODAY }),
    );
    expect(after.sort()).toEqual(before.sort());
  });

  it("IN-12: long keys are cut to 200 characters and stay unique", () => {
    const skills = Array.from({ length: 30 }, (_, n) => `Skill number ${n}`);
    const issues = checkResume(cv([role({ end: null, skills })]), { today: TODAY });
    const key = find(issues, "consistency.skills-missing:")!.key;
    expect(key.length).toBe(200);
    expect(fitKey(key)).toBe(key);
    expect(fitKey("x".repeat(300))).not.toBe(fitKey(`${"x".repeat(299)}y`));
  });

  it("IN-12: the same company and title twice get distinct ids", () => {
    expect(roleIds([role({}), role({})])).toEqual(["acme/product-manager", "acme/product-manager#2"]);
  });
});

describe("helpers", () => {
  it("IN-3: works out the length of a role", () => {
    expect(spanLength("2022-03", null, TODAY)).toBe("4 years 8 months");
    expect(spanLength("2014", "2016", TODAY)).toBe("about 2 years");
    expect(formatSpan("2022-03", "2024-09", TODAY)).toBe("Mar 2022 to Sep 2024 · 2 years 7 months");
  });

  it("IN-3: sorts roles newest first and groups long skill lists", () => {
    const sorted = newestFirst([
      role({ company: "old", start: "2014", end: "2016" }),
      role({ company: "now", start: "2022-03", end: null }),
      role({ company: "mid", start: "2017-01", end: "2019-02" }),
    ]);
    expect(sorted.map((r) => r.company)).toEqual(["now", "mid", "old"]);
    expect(groupSkills(["SQL", "Payments", "Stakeholder management", "Figma"])).toEqual([
      { group: "Tools", skills: ["SQL", "Figma"] },
      { group: "Domain", skills: ["Payments"] },
      { group: "Ways of working", skills: ["Stakeholder management"] },
    ]);
  });
});
