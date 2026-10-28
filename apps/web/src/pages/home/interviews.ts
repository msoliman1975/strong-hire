/** Display helpers for the v2 Home (PP-3, PR-2). */
import type { JobTargetSummary, PlannedSession } from "../../api/types";
import { difficultyLabel, interviewTypeLabel } from "../../labels";

export function jobRole(s: JobTargetSummary): string {
  const job = s.job_target;
  return job.name ?? (job.posting ? job.posting.title : "Job posting");
}

export function jobCompany(s: JobTargetSummary): string {
  const job = s.job_target;
  return job.posting?.company_name ?? job.source_url ?? "Reading the posting";
}

/**
 * The interview date, when the API sends one. `JobTarget.interview_date` exists in the database;
 * the plan page stream (S10) adds it to the job API. Until then this is null.
 */
export function interviewDate(s: JobTargetSummary): string | null {
  const job = s.job_target as { interview_date?: string | null };
  return job.interview_date ?? null;
}

/** Whole days from today to a YYYY-MM-DD date, in the browser's time zone. */
export function daysUntil(date: string, today: Date = new Date()): number {
  const [y, m, d] = date.slice(0, 10).split("-").map(Number);
  const target = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - now) / 86_400_000);
}

/** Ready to rehearse: the posting is read and the gap analysis has a match score. */
export const isReady = (s: JobTargetSummary) => s.job_target.status !== "pending" && s.match_score !== null;

/**
 * The interview the coach talks about: the soonest one still ahead, else the one practiced last,
 * else the first in the list.
 */
export function focusInterview(jobs: JobTargetSummary[], today: Date = new Date()): JobTargetSummary | null {
  const ahead = jobs
    .map((s) => ({ s, days: interviewDate(s) === null ? null : daysUntil(interviewDate(s) as string, today) }))
    .filter((x): x is { s: JobTargetSummary; days: number } => x.days !== null && x.days >= 0)
    .sort((a, b) => a.days - b.days);
  if (ahead.length > 0) return ahead[0].s;
  const practiced = jobs.filter((s) => s.last_session_at !== null);
  practiced.sort((a, b) => (b.last_session_at ?? "").localeCompare(a.last_session_at ?? ""));
  return practiced[0] ?? jobs[0] ?? null;
}

/** PR-2 as one sentence from the coach. */
export function coachAdvice(
  summary: JobTargetSummary | null,
  next: PlannedSession | null,
  today: Date = new Date(),
): string {
  if (!summary) return "Add the job you are interviewing for, and I will plan your practice around it.";
  const company = jobCompany(summary);
  if (!isReady(summary)) return `Finish setting up ${company}, and I will plan your first rehearsal.`;
  const date = interviewDate(summary);
  const days = date === null ? null : daysUntil(date, today);
  const lead =
    days !== null && days >= 0
      ? `Your ${company} interview is ${days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`}`
      : `For ${company}`;
  if (!next) return `${lead}: run a rehearsal and I will tell you what to work on next.`;
  const focus = next.focus_topics.length > 0 ? `, on ${next.focus_topics.slice(0, 2).join(" and ")}` : "";
  const kind = `${interviewTypeLabel[next.interview_type]} at ${difficultyLabel[next.difficulty]} difficulty`;
  return `${lead}: practice ${kind} next${focus}.`;
}
