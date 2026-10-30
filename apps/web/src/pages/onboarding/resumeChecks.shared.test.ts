/**
 * RM-5: the web check and the API check (apps/api/src/strong_api/resume_checks/checks.py) give
 * the same results. Both run the shared cases in apps/api/tests/fixtures/resume_checks/cases.json.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { JobPosting, Resume } from "../../api/types";
import { checkResume, type ResumeIssue } from "./resumeChecks";

interface SharedCase {
  name: string;
  resume: Resume;
  today: string;
  job: JobPosting | null;
  expected: ResumeIssue[];
}

const FILE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../api/tests/fixtures/resume_checks/cases.json",
);
const CASES = JSON.parse(readFileSync(FILE, "utf-8")) as SharedCase[];

describe("RM-5 shared resume check cases", () => {
  it("RM-5: the shared file has cases", () => {
    expect(CASES.length).toBeGreaterThan(20);
  });

  it.each(CASES.map((c) => [c.name, c] as const))("RM-5: %s", (_name, c) => {
    // JSON drops undefined fields, so compare through JSON on both sides.
    const got = JSON.parse(JSON.stringify(checkResume(c.resume, { today: c.today, job: c.job })));
    expect(got).toEqual(c.expected);
  });
});
