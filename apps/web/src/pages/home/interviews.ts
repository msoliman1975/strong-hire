/** Display helpers for the v2 Home (PP-3, PR-2). */
import type { Competency, JobTargetSummary, PlannedSession } from "../../api/types";
import { competencyLabel, difficultyLabel, interviewTypeLabel } from "../../labels";

export function jobRole(s: JobTargetSummary): string {
  const job = s.job_target;
  const name = job.name ?? (job.posting ? job.posting.title : "Job posting");
  // The default job name is "<title> at <company>"; the card shows the company after a dot.
  const company = job.posting?.company_name;
  return company && name.endsWith(` at ${company}`) ? name.slice(0, -` at ${company}`.length) : name;
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
  /** Days left from the plan page (PP-2), when Home has it; else the job's own date. */
  daysLeft?: number | null,
): string {
  if (!summary) return "Add the job you are interviewing for, and I will plan your practice around it.";
  const company = jobCompany(summary);
  if (!isReady(summary)) return `Finish setting up ${company}, and I will plan your first rehearsal.`;
  const date = interviewDate(summary);
  const days = daysLeft ?? (date === null ? null : daysUntil(date, today));
  const when = whenText(days);
  const lead = when ? `Your ${company} interview is ${when}` : `For ${company}`;
  if (!next) return `${lead}: run a rehearsal and I will tell you what to work on next.`;
  const focus = next.focus_topics.length > 0 ? `, on ${next.focus_topics.slice(0, 2).join(" and ")}` : "";
  const kind = `${interviewTypeLabel[next.interview_type]} at ${difficultyLabel[next.difficulty]} difficulty`;
  return `${lead}: practice ${kind} next${focus}.`;
}

/** "in 6 days", "tomorrow", "today"; null for a date that passed or is not set. */
export function whenText(days: number | null): string | null {
  if (days === null || days < 0) return null;
  return days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
}

/** A story gap the coach can help with: a tested skill with no story, or only Draft stories. */
export interface StoryGap {
  skill: Competency;
  state: "missing" | "thin";
}

/**
 * The canvas Home nudge: the interview in focus and its first story gap, as one sentence. With no
 * gap it falls back to the PR-2 next-session advice.
 */
export function coachNudge(
  summary: JobTargetSummary | null,
  gap: StoryGap | null,
  next: PlannedSession | null,
  days: number | null,
  today: Date = new Date(),
): string {
  if (!summary || !isReady(summary) || !gap) return coachAdvice(summary, next, today, days);
  const when = whenText(days);
  const lead = when ? `Your ${jobCompany(summary)} interview is ${when}` : `For your ${jobCompany(summary)} interview`;
  const skill = competencyLabel(gap.skill).toLowerCase();
  return gap.state === "missing"
    ? `${lead}, and you don't have a ${skill} story yet. Want to build one now?`
    : `${lead}, and your ${skill} story is not proven yet. Want to sharpen it now?`;
}
