/** Links between the rehearsal steps. Display routing only. */

/** The context step starts the gap analysis with the chosen resume. */
export const contextPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/context?resume=${encodeURIComponent(resumeId)}`;

/** "Check your CV" inside a rehearsal: confirm the extracted CV before the gap analysis. */
export const checkPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/resume/${encodeURIComponent(resumeId)}/check`;

/**
 * "Check your CV" from the Resumes page (LB-1), with no job. `task` is the reading job of a new
 * upload, so a refused CV shows why (IN-7).
 */
export const resumeCheckPath = (resumeId: string, task?: string | null) =>
  `/resumes/${encodeURIComponent(resumeId)}/check${task ? `?task=${encodeURIComponent(task)}` : ""}`;

/** PR-3: one job and CV pair, with its earlier reports. */
export const rehearsalPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/rehearse/${encodeURIComponent(resumeId)}`;

/** Where "Add a job description" returns: the Job descriptions page, or on to the resume step. */
export type NewJobReturn = "library" | "rehearsal";
export const newJobPath = (then: NewJobReturn) => (then === "library" ? "/jobs/new?then=library" : "/jobs/new");

/** QB-1, QB-4: the Questions page with filters in the URL. */
export function questionsPath(filter: {
  company?: string | null;
  interviewType?: string | null;
  competencies?: string[];
}): string {
  const params = new URLSearchParams();
  if (filter.company) params.set("company", filter.company);
  if (filter.interviewType) params.set("type", filter.interviewType);
  for (const c of filter.competencies ?? []) params.append("area", c);
  const query = params.toString();
  return query ? `/questions?${query}` : "/questions";
}
