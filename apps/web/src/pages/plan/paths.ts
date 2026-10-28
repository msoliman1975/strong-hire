/** PP-1: the interview plan page of one job and CV pair. */
export const planPath = (jobId: string, resumeId: string) =>
  `/interviews/${encodeURIComponent(jobId)}/${encodeURIComponent(resumeId)}`;
