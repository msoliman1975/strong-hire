/** The Custom setup rules the screen enforces (CU-1, CU-3, D-3, D-5). */
import { describe, expect, it } from "vitest";

import { categoryBlock, evenShares, fromSpecShares, planSummary, setShare, setupProblems, type CategoryShare } from "./rules";

const total = (shares: CategoryShare[]) => shares.reduce((n, s) => n + s.share, 0);

describe("Custom setup rules", () => {
  it("CU-1: the default split is even in 5% steps and adds up to 100", () => {
    expect(evenShares(["behavioral"]).map((s) => s.share)).toEqual([100]);
    expect(evenShares(["behavioral", "technical_qa"]).map((s) => s.share)).toEqual([50, 50]);
    expect(evenShares(["behavioral", "technical_qa", "hiring_manager"]).map((s) => s.share)).toEqual([35, 35, 30]);
    expect(evenShares(["case", "behavioral"]).map((s) => s.share)).toEqual([50, 50]);
  });

  it("CU-1: moving one share moves the others, keeps 100% and the 15% minimum", () => {
    const three = evenShares(["behavioral", "technical_qa", "hiring_manager"]);
    const more = setShare(three, 0, 60);
    expect(more.map((s) => s.share)).toEqual([60, 25, 15]);
    expect(total(more)).toBe(100);
    // The most a category can take while the other two keep 15% each.
    const max = setShare(three, 0, 95);
    expect(max.map((s) => s.share)).toEqual([70, 15, 15]);
    const less = setShare(three, 0, 0);
    expect(less[0].share).toBe(15);
    expect(total(less)).toBe(100);
    expect(setShare(three, 1, 42).every((s) => s.share % 5 === 0)).toBe(true);
  });

  it("D-3: Case keeps at least half the time when mixed", () => {
    const shares = evenShares(["case", "behavioral"]);
    expect(setShare(shares, 0, 20).map((s) => s.share)).toEqual([50, 50]);
    expect(setShare(shares, 1, 80).map((s) => s.share)).toEqual([50, 50]);
    expect(setShare(shares, 0, 85).map((s) => s.share)).toEqual([85, 15]);
  });

  it("D-3: Case needs 45 minutes and at most one other kind; at most 3 kinds", () => {
    expect(categoryBlock("case", [], 30)).toMatch(/needs a 45-minute session/);
    expect(categoryBlock("case", [], 45)).toBeNull();
    expect(categoryBlock("case", ["behavioral", "technical_qa"], 45)).toMatch(/at most one other/);
    expect(categoryBlock("hiring_manager", ["case", "behavioral"], 45)).toMatch(/one other kind/);
    expect(categoryBlock("case", ["behavioral", "technical_qa", "hiring_manager"], 45)).toMatch(/at most 3/);
    expect(categoryBlock("behavioral", ["behavioral"], 30)).toBeNull();
  });

  it("CU-3, D-5: own questions are capped at 5 for 30 minutes and 8 for 45", () => {
    const one = evenShares(["behavioral"]);
    expect(setupProblems(one, 5, 30)).toEqual([]);
    expect(setupProblems(one, 6, 30)[0]).toMatch(/up to 5/);
    expect(setupProblems(one, 8, 45)).toEqual([]);
    expect(setupProblems([], 0, 30)).toEqual(["Pick at least one kind of question."]);
    expect(setupProblems(evenShares(["case"]), 0, 30)).toContain("A case needs a 45-minute session.");
  });

  it("the summary counts the candidate's and the interviewer's questions", () => {
    expect(planSummary(30, 3)).toBe("About 8 questions: 3 of yours, 5 chosen by the interviewer from your focus areas.");
    expect(planSummary(45, 0)).toBe("About 10 questions: 0 of yours, 10 chosen by the interviewer from your focus areas.");
  });

  it("CU-9: shares from a repeated setup come back as whole percents adding up to 100", () => {
    const shares = fromSpecShares([
      { category: "behavioral", share: 0.34, focus: [] },
      { category: "technical_qa", share: 0.33, focus: [] },
      { category: "hiring_manager", share: 0.33, focus: [] },
    ]);
    expect(total(shares)).toBe(100);
    expect(shares.every((s) => s.share % 5 === 0)).toBe(true);
  });
});
