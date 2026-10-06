/**
 * Job and resume inputs (P2). These endpoints exist in the API, so they use the typed client.
 *
 * Create and update calls return 202 with a background job. The app polls the job until its
 * status is "complete", then reads `result.outcome`: "extracted", "needs_paste" (the URL cannot
 * be read; the user pastes the text) or "failed" (with a reason).
 */
import { apiClient, unwrap } from "./client";
import type {
  JobOut,
  JobTargetAccepted,
  JobTargetCreate,
  JobTargetOut,
  JobTargetSummary,
  JobTargetUpdate,
  Resume,
  ResumeAccepted,
  ResumeOut,
} from "./types";

export const jobTargetsApi = {
  /** The signed-in user's jobs, newest first, with the dashboard numbers. */
  list: async () => unwrap(await apiClient.GET("/job-targets")) as JobTargetSummary[],
  /** IN-1. HTTP 422 with detail.code "paste_required" when the site cannot be read (LinkedIn). */
  create: async (body: JobTargetCreate) =>
    unwrap(await apiClient.POST("/job-targets", { body })) as JobTargetAccepted,
  get: async (jobTargetId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}", {
        params: { path: { job_target_id: jobTargetId } },
      }),
    ) as JobTargetOut,
  /** IN-2 and IN-4: save the confirmed posting, the stage and the context together. */
  update: async (jobTargetId: string, body: JobTargetUpdate) =>
    unwrap(
      await apiClient.PUT("/job-targets/{job_target_id}", {
        params: { path: { job_target_id: jobTargetId } },
        body,
      }),
    ) as JobTargetAccepted,
  job: async (jobTargetId: string, jobId: string) =>
    unwrap(
      await apiClient.GET("/job-targets/{job_target_id}/jobs/{job_id}", {
        params: { path: { job_target_id: jobTargetId, job_id: jobId } },
      }),
    ) as JobOut,
};

export const resumesApi = {
  /** The signed-in user's resumes, newest first. */
  list: async () => unwrap(await apiClient.GET("/resumes")) as ResumeOut[],
  /** IN-3. Multipart form: either a `file` (PDF or DOCX) or a `text` field. */
  upload: async (form: FormData) =>
    unwrap(
      await apiClient.POST("/resumes", {
        // The generated type describes the form fields; the browser sends the FormData as is.
        body: form as never,
        bodySerializer: (body: unknown) => body as FormData,
      }),
    ) as ResumeAccepted,
  get: async (resumeId: string) =>
    unwrap(
      await apiClient.GET("/resumes/{resume_id}", { params: { path: { resume_id: resumeId } } }),
    ) as ResumeOut,
  update: async (resumeId: string, resume: Resume) =>
    unwrap(
      await apiClient.PUT("/resumes/{resume_id}", {
        params: { path: { resume_id: resumeId } },
        body: { resume },
      }),
    ) as ResumeOut,
  job: async (resumeId: string, jobId: string) =>
    unwrap(
      await apiClient.GET("/resumes/{resume_id}/jobs/{job_id}", {
        params: { path: { resume_id: resumeId, job_id: jobId } },
      }),
    ) as JobOut,
};

/** True while a background job still runs. */
export const jobRunning = (job: JobOut | undefined) =>
  job === undefined || job.status === "queued" || job.status === "in_progress";

/**
 * Why a finished background job did not produce data, in words for the user. Null when it worked.
 * Display only: the worker decides the outcome.
 */
export function jobProblem(job: JobOut | undefined): { needsPaste: boolean; message: string } | null {
  if (!job || jobRunning(job)) return null;
  if (job.status === "failed") return { needsPaste: false, message: job.error ?? "The background job failed." };
  if (job.status === "not_found") return { needsPaste: false, message: "The background job has expired." };
  const result = job.result ?? {};
  const outcome = result.outcome;
  const detail = typeof result.detail === "string" ? result.detail : null;
  const reason = typeof result.reason === "string" ? result.reason : null;
  if (outcome === "needs_paste") {
    return { needsPaste: true, message: detail ?? "We could not read that link. Paste the job posting text." };
  }
  if (outcome === "failed") return { needsPaste: false, message: reason ?? "We could not read it." };
  return null;
}
