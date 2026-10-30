/** IN-12: the short state of a saved CV, worked out from the saved CV with the check rules. */
import { describe, expect, it } from "vitest";

import type { ResumeOut } from "../../api/types";
import { resume as fixtureResume } from "../../mocks/fixtures";
import { checkResume } from "./resumeChecks";
import { checkedLabel, countIssues, issueSummary, issuesOpen, resumeIssueCounts, shortDate } from "./resumeSummary";

const record = (over: Partial<ResumeOut> = {}): ResumeOut => ({
  id: "r1",
  name: "Ana CV",
  deleted: false,
  status: "extracted",
  has_file: false,
  resume: fixtureResume,
  confirmed_at: null,
  uploaded_at: "2026-10-01T10:00:00Z",
  accepted_issues: [],
  is_main: true,
  ...over,
});

describe("resume summary", () => {
  it("IN-12: counts open, accepted and high issues, and ignores accepted keys the rules no longer find", () => {
    const issues = checkResume(fixtureResume, { today: "2026-10" });
    const first = issues[0];
    const counts = countIssues(issues, new Set([first.key, "detail.gone:old"]));
    expect(counts.accepted).toBe(1);
    expect(counts.open).toBe(issues.length - 1);
    expect(counts.high).toBe(issues.filter((i) => i.key !== first.key && i.severity === "high").length);
    expect(issueSummary({ open: 3, accepted: 1, high: 0 })).toBe("3 to fix · 1 accepted · 0 high");
    expect(issuesOpen(1)).toBe("1 issue open");
    expect(issuesOpen(4)).toBe("4 issues open");
  });

  it("IN-12: the same saved CV gives the same issues and recommendations every time", () => {
    const a = checkResume(fixtureResume, { today: "2026-10" });
    const b = checkResume(structuredClone(fixtureResume), { today: "2026-10" });
    expect(b).toEqual(a);
    expect(a.every((i) => i.why && i.fixLabel)).toBe(true);
  });

  it("IN-12: applies the saved accepted issues, and has no counts while the CV is being read", () => {
    const key = checkResume(fixtureResume, { today: "2026-10" })[0].key;
    const counts = resumeIssueCounts(
      record({ accepted_issues: [{ key, accepted_at: "2026-10-28T10:00:00Z" }] }),
      "2026-10",
    );
    expect(counts?.accepted).toBe(1);
    expect(resumeIssueCounts(record({ status: "pending", resume: null }))).toBeNull();
  });

  it("IN-12: says when the CV was checked", () => {
    const now = new Date("2026-11-02T10:00:00Z");
    expect(shortDate("2026-10-28T10:00:00Z", now)).toBe("Oct 28");
    expect(shortDate("2025-10-28T10:00:00Z", now)).toBe("Oct 28, 2025");
    expect(checkedLabel({ confirmed_at: null })).toBe("Not checked yet");
    expect(checkedLabel({ confirmed_at: `${new Date().getFullYear()}-10-28T10:00:00Z` })).toBe("Checked Oct 28");
  });
});
