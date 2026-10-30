/**
 * Job and resume inputs (P2). These endpoints exist in the API, so they use the typed client.
 *
 * Create and update calls return 202 with a background job. The app polls the job until its
 * status is "complete", then reads `result.outcome`: "extracted", "needs_paste" (the URL cannot
 * be read; the user pastes the text), "rejected" (the input is not a job description, IN-6, or not
 * a CV, IN-7; `reason` says why) or "failed" (with a reason).
 */
import { apiClient, unwrap } from "./client";
import type {
  JobOut,
  JobTargetAccepted,
  JobTargetCreate,
  JobTargetMatch,
  JobTargetMatchIn,
  JobTargetOut,
  JobTargetSummary,
  JobTargetUpdate,
  Resume,
  ResumeAccepted,
  ResumeIssues,
  ResumeMatch,
  ResumeOut,
  StoryIdeasOut,
} from "./types";

export const jobTargetsApi = {
  /** The signed-in user's jobs, newest first, with the dashboard numbers. Archived ones only on request (LB-2). */
  list: async (includeArchived = false) =>
    unwrap(
      await apiClient.GET("/job-targets", { params: { query: { include_archived: includeArchived } } }),
    ) as JobTargetSummary[],
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
  /** R1: the saved job with the same posting text or link, so it is not read again. */
  match: async (body: JobTargetMatchIn) =>
    unwrap(await apiClient.POST("/job-targets/match", { body })) as JobTargetMatch,
  /** R1: rename a saved job. HTTP 422 when the name is empty or longer than 120 characters. */
  rename: async (jobTargetId: string, name: string) =>
    unwrap(
      await apiClient.PATCH("/job-targets/{job_target_id}", {
        params: { path: { job_target_id: jobTargetId } },
        body: { name },
      }),
    ) as JobTargetOut,
  /** LB-2: archive a job description that has reports. It and its reports stay. */
  archive: async (jobTargetId: string) =>
    unwrap(
      await apiClient.POST("/job-targets/{job_target_id}/archive", {
        params: { path: { job_target_id: jobTargetId } },
      }),
    ) as JobTargetOut,
  /** LB-2: bring an archived job description back. */
  restore: async (jobTargetId: string) =>
    unwrap(
      await apiClient.POST("/job-targets/{job_target_id}/restore", {
        params: { path: { job_target_id: jobTargetId } },
      }),
    ) as JobTargetOut,
  /** R1, LB-2: delete a job description that has no reports. HTTP 409 when it has reports. */
  remove: async (jobTargetId: string) => {
    unwrap(
      await apiClient.DELETE("/job-targets/{job_target_id}", {
        params: { path: { job_target_id: jobTargetId } },
        parseAs: "text",
      }),
    );
  },
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
  /** IN-12: accept a CV check issue, or clear it with accepted false. */
  setAcceptedIssue: async (resumeId: string, key: string, accepted: boolean) =>
    unwrap(
      await apiClient.PUT("/resumes/{resume_id}/accepted-issues", {
        params: { path: { resume_id: resumeId } },
        body: { key, accepted },
      }),
    ) as ResumeOut,
  job: async (resumeId: string, jobId: string) =>
    unwrap(
      await apiClient.GET("/resumes/{resume_id}/jobs/{job_id}", {
        params: { path: { resume_id: resumeId, job_id: jobId } },
      }),
    ) as JobOut,
  /** R1: the saved CV with the same content. `sha256` is the hash of the file or the pasted text. */
  match: async (sha256: string) =>
    unwrap(await apiClient.POST("/resumes/match", { body: { sha256 } })) as ResumeMatch,
  rename: async (resumeId: string, name: string) =>
    unwrap(
      await apiClient.PATCH("/resumes/{resume_id}", {
        params: { path: { resume_id: resumeId } },
        body: { name },
      }),
    ) as ResumeOut,
  /** RM-2: make this the main resume. */
  setMain: async (resumeId: string) =>
    unwrap(
      await apiClient.POST("/resumes/{resume_id}/main", { params: { path: { resume_id: resumeId } } }),
    ) as ResumeOut,
  /** RM-5: the API's resume check, open and accepted issues. */
  issues: async (resumeId: string, jobTargetId?: string | null) =>
    unwrap(
      await apiClient.GET("/resumes/{resume_id}/issues", {
        params: { path: { resume_id: resumeId }, query: jobTargetId ? { job_target_id: jobTargetId } : {} },
      }),
    ) as ResumeIssues,
  /** RM-4: story ideas from the resume's achievements. */
  storyIdeas: async (resumeId: string) =>
    unwrap(
      await apiClient.GET("/resumes/{resume_id}/story-ideas", { params: { path: { resume_id: resumeId } } }),
    ) as StoryIdeasOut,
  /** RM-4: "Not a story". */
  dismissIdea: async (resumeId: string, resumeLineRef: string) => {
    unwrap(
      await apiClient.POST("/resumes/{resume_id}/story-ideas/dismiss", {
        params: { path: { resume_id: resumeId } },
        body: { resume_line_ref: resumeLineRef },
        parseAs: "text",
      }),
    );
  },
  /** R1: delete a saved CV and its stored file. Its gap reports stay. */
  remove: async (resumeId: string) => {
    unwrap(
      await apiClient.DELETE("/resumes/{resume_id}", {
        params: { path: { resume_id: resumeId } },
        parseAs: "text",
      }),
    );
  },
};

/** SHA-256 as hex, the same hash the API keeps for a CV (R1). */
export async function sha256Hex(data: ArrayBuffer | string): Promise<string> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** True while a background job still runs. */
export const jobRunning = (job: JobOut | undefined) =>
  job === undefined || job.status === "queued" || job.status === "in_progress";

/**
 * Why a finished background job did not produce data, in words for the user. Null when it worked.
 * Display only: the worker decides the outcome.
 */
export interface JobProblem {
  needsPaste: boolean;
  /** IN-6, IN-7: the input is not a job description or not a CV. */
  refused: boolean;
  message: string;
}

export function jobProblem(job: JobOut | undefined): JobProblem | null {
  if (!job || jobRunning(job)) return null;
  const problem = (message: string, needsPaste = false, refused = false) => ({ needsPaste, refused, message });
  if (job.status === "failed") return problem(job.error ?? "The background job failed.");
  if (job.status === "not_found") return problem("The background job has expired.");
  const result = job.result ?? {};
  const outcome = result.outcome;
  const detail = typeof result.detail === "string" ? result.detail : null;
  const reason = typeof result.reason === "string" ? result.reason : null;
  if (outcome === "needs_paste") {
    return problem(detail ?? "We could not read that link. Paste the job posting text.", true);
  }
  if (outcome === "rejected") return problem(reason ?? "This is not the kind of document we expected.", false, true);
  if (outcome === "failed") return problem(reason ?? "We could not read it.");
  return null;
}
