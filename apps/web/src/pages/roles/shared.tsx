/** Small pieces the role, rehearsal and interview screens share (U07). */
import type { InterviewWithReadiness, ResumeOut, RoleSummary } from "../../api/types";
import { interviewTypeLabel } from "../../labels";

export const rolesPath = "/roles";
export const addRolePath = "/roles/new";
export const rolePath = (jobId: string) => `/roles/${jobId}`;
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

/** "Main resume", or the resume's name. */
export function resumeLabel(resumes: ResumeOut[] | undefined, resumeId: string | undefined): string {
  const r = resumes?.find((x) => x.id === resumeId);
  if (!r) return "Resume";
  return r.is_main ? "Main resume" : (r.name ?? "Resume");
}

export const typeName = (i: InterviewWithReadiness["interview"]) => interviewTypeLabel[i.interview_type];

/** One readiness bar: "Behavioral 58" or "Not started". */
export function ReadinessRow({ item }: { item: InterviewWithReadiness }) {
  const score = item.readiness.score;
  return (
    <div>
      <div className="sx-between sx-small">
        <span>{typeName(item.interview)}</span>
        {score === null ? <span className="sx-muted">Not started</span> : <span className="sx-mono">{score}</span>}
      </div>
      <div className="sx-bar" role="meter" aria-label={`${typeName(item.interview)} readiness`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={score ?? 0}>
        <span style={{ width: `${score ?? 0}%` }} />
      </div>
    </div>
  );
}

/** "3 takes · last: Hire", "Not started". */
export function takesMeta(item: InterviewWithReadiness): string {
  if (item.takes_count === 0) return "Not started";
  const takes = `${item.takes_count} ${item.takes_count === 1 ? "take" : "takes"}`;
  return item.last_signal ? `${takes} · last: ${item.last_signal}` : takes;
}
