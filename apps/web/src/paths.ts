/** Links between the rehearsal steps. Display routing only. */

/** The context step starts the gap analysis with the chosen resume. */
export const contextPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/context?resume=${encodeURIComponent(resumeId)}`;

/** "Check your CV" inside a rehearsal: confirm the extracted CV before the gap analysis. */
export const checkPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/resume/${encodeURIComponent(resumeId)}/check`;

/** "Check your CV" from the Resumes page (LB-1), with no job. */
export const resumeCheckPath = (resumeId: string) => `/resumes/${encodeURIComponent(resumeId)}/check`;

/** PR-3: one job and CV pair, with its earlier reports. */
export const rehearsalPath = (jobId: string, resumeId: string) =>
  `/jobs/${jobId}/rehearse/${encodeURIComponent(resumeId)}`;

/** Where "Add a job description" returns: the Job descriptions page, or on to the resume step. */
export type NewJobReturn = "library" | "rehearsal";
export const newJobPath = (then: NewJobReturn) => (then === "library" ? "/jobs/new?then=library" : "/jobs/new");
