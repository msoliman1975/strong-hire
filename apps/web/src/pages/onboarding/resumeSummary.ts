/**
 * IN-12: the short state of a saved CV, for the Resumes list, the Home card and the check page.
 * Everything here comes from the saved CV and its accepted issues: the issues are recomputed with
 * the same rules as the check page (resumeChecks.ts), so nothing else needs storing.
 */
import type { ResumeOut } from "../../api/types";
import { acceptedKeySet } from "./acceptedIssues";
import { checkResume, thisMonth, type ResumeIssue } from "./resumeChecks";

export interface IssueCounts {
  /** Issues not accepted: the ones left to fix. */
  open: number;
  /** Accepted issues that the rules still find. A stale accepted key is not counted. */
  accepted: number;
  /** Open issues with high severity. */
  high: number;
}

export function countIssues(issues: readonly ResumeIssue[], accepted: ReadonlySet<string>): IssueCounts {
  const open = issues.filter((i) => !accepted.has(i.key));
  return {
    open: open.length,
    accepted: issues.length - open.length,
    high: open.filter((i) => i.severity === "high").length,
  };
}

/** The counts for a saved CV, with no job. Null while the CV is still being read. */
export function resumeIssueCounts(record: ResumeOut, today = thisMonth()): IssueCounts | null {
  if (!record.resume) return null;
  const issues = checkResume(record.resume, { today, job: null });
  return countIssues(issues, acceptedKeySet(record.accepted_issues));
}

/** "3 to fix · 1 accepted · 0 high". */
export function issueSummary(c: IssueCounts): string {
  return `${c.open} to fix · ${c.accepted} accepted · ${c.high} high`;
}

/** "1 issue open", "3 issues open". */
export const issuesOpen = (n: number) => `${n} ${n === 1 ? "issue" : "issues"} open`;

/** "Oct 28", with the year when it is not this year. */
export function shortDate(iso: string, now = new Date()): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/**
 * RMAP-3: "Edited Oct 28" from confirmed_at, else null. confirmed_at is set when the user saves the
 * resume from the editor; the issues are found on every read, saved or not. So a resume never
 * saved says nothing here, instead of a "Not checked yet" next to its issue counts.
 */
export const editedLabel = (record: Pick<ResumeOut, "confirmed_at">): string | null =>
  record.confirmed_at ? `Edited ${shortDate(record.confirmed_at)}` : null;
