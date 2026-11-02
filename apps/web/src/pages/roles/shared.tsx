/** Small pieces the role, rehearsal and interview screens share (U07). */
import type { InterviewWithReadiness, ResumeOut, RoleSummary } from "../../api/types";
import { ReadinessRing } from "../../components/ux/ReadinessRing";
import { interviewTypeLabel } from "../../labels";

export const rolesPath = "/roles";
export const addRolePath = "/roles/new";
export const rolePath = (jobId: string) => `/roles/${jobId}`;
/** A take's default length in minutes: the mini interview every plan can run. */
export const DEFAULT_TAKE_MINUTES = 10;
export const interviewPath = (interviewId: string) => `/interviews/${interviewId}`;

/** "Stripe · Senior Software Engineer, Payments", or the library name. */
export function roleTitle(role: RoleSummary): string {
  if (role.company_name && role.title) return `${role.company_name} · ${role.title}`;
  return role.name ?? role.title ?? "Target role";
}

/** The date chip: "Onsite in 6 days", "Interview today", or "No date yet". */
export function dateChip(role: RoleSummary, stage?: string | null): { text: string; teal: boolean } {
  const d = role.days_left;
  if (d === null || d === undefined) return { text: "No date yet", teal: false };
  const what = stage?.trim() || "Interview";
  if (d < 0) return { text: `${what} was ${-d} ${-d === 1 ? "day" : "days"} ago`, teal: false };
  if (d === 0) return { text: `${what} today`, teal: true };
  return { text: `${what} in ${d} ${d === 1 ? "day" : "days"}`, teal: true };
}

/**
 * RMAP-5: the role's resume was deleted (or is missing from the user's resumes). False while the
 * resumes load or when there is no resume id, so nothing flashes.
 */
export function resumeGone(resumes: ResumeOut[] | undefined, resumeId: string | null | undefined): boolean {
  if (!resumes || !resumeId) return false;
  return !resumes.some((r) => r.id === resumeId && !r.deleted);
}

/** "Default resume", the resume's name, or "Resume deleted" (RMAP-5). */
export function resumeLabel(resumes: ResumeOut[] | undefined, resumeId: string | undefined): string {
  if (resumeGone(resumes, resumeId)) return "Resume deleted";
  const r = resumes?.find((x) => x.id === resumeId);
  if (!r) return "Resume";
  return r.is_main ? "Default resume" : (r.name ?? "Resume");
}

export const typeName = (i: InterviewWithReadiness["interview"]) => interviewTypeLabel[i.interview_type];

/** One readiness row: a small readiness ring (SV-11), then "Behavioral 58" or "Not started". */
export function ReadinessRow({ item }: { item: InterviewWithReadiness }) {
  const score = item.readiness.score;
  return (
    <div className="sx-row sx-small" style={{ gap: 8, alignItems: "center" }}>
      <ReadinessRing score={score} goal={item.readiness.goal} size={24} label={`${typeName(item.interview)} readiness`} />
      <span style={{ flex: 1 }}>{typeName(item.interview)}</span>
      {score === null ? <span className="sx-muted">Not started</span> : <span className="sx-mono">{score}</span>}
    </div>
  );
}

/** "3 takes · last: Hire", "Not started". */
export function takesMeta(item: InterviewWithReadiness): string {
  if (item.takes_count === 0) return "Not started";
  const takes = `${item.takes_count} ${item.takes_count === 1 ? "take" : "takes"}`;
  return item.last_signal ? `${takes} · last: ${item.last_signal}` : takes;
}
