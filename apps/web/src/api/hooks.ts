import { useQuery } from "@tanstack/react-query";

import { authApi } from "./auth";
import { billingApi } from "./billing";
import { devApi } from "./dev";
import { gapApi } from "./gap";
import { jobRunning, jobTargetsApi, resumesApi } from "./inputs";
import { sessionsApi } from "./sessions";
import { debriefApi } from "./scoring";

/** How often to re-check work that runs in the background (extraction, analysis, scoring). */
export const POLL_MS = 1000;

export const keys = {
  me: ["auth", "me"] as const,
  providers: ["auth", "providers"] as const,
  usage: ["billing", "usage"] as const,
  plan: ["billing", "plan"] as const,
  modelUsage: ["dev", "model-usage"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["jobs", id] as const,
  jobTask: (id: string, taskId: string) => ["jobs", id, "task", taskId] as const,
  jobSessions: (id: string) => ["jobs", id, "sessions"] as const,
  gap: (id: string) => ["jobs", id, "gap"] as const,
  progress: (id: string) => ["jobs", id, "progress"] as const,
  resumes: ["resumes"] as const,
  resume: (id: string) => ["resumes", id] as const,
  resumeTask: (id: string, taskId: string) => ["resumes", id, "task", taskId] as const,
  session: (id: string) => ["sessions", id] as const,
  debrief: (id: string) => ["sessions", id, "debrief"] as const,
};

export const useAuth = () => useQuery({ queryKey: keys.me, queryFn: authApi.me, staleTime: 30_000 });

export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: authApi.providers, staleTime: Infinity });

export const useUsage = (enabled = true) =>
  useQuery({ queryKey: keys.usage, queryFn: billingApi.usage, enabled });

/**
 * Claude spend against the LiteLLM budgets, refreshed every 30 seconds. The API answers in dev and,
 * on the hosted test server, only for the owner (MODEL_SPEND_VIEWERS). Anyone else gets 404: the
 * meter stays hidden and the page stops asking.
 */
export const useModelUsage = (enabled = true) =>
  useQuery({
    queryKey: keys.modelUsage,
    queryFn: devApi.modelUsage,
    enabled,
    refetchInterval: (q) => (q.state.status === "error" ? false : 30_000),
    retry: false,
  });

export const usePlan = () => useQuery({ queryKey: keys.plan, queryFn: billingApi.plan });

export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: jobTargetsApi.list });

/** A job target. Polls while the posting is still being read, unless `poll` is false. */
export const useJob = (jobId: string, poll = true) =>
  useQuery({
    queryKey: keys.job(jobId),
    queryFn: () => jobTargetsApi.get(jobId),
    refetchInterval: (q) => (poll && q.state.data?.status === "pending" ? POLL_MS : false),
  });

/** The background job that reads a posting. `taskId` comes from the create or update response. */
export const useJobTask = (jobId: string, taskId: string | null) =>
  useQuery({
    queryKey: keys.jobTask(jobId, taskId ?? ""),
    queryFn: () => jobTargetsApi.job(jobId, taskId ?? ""),
    enabled: Boolean(taskId),
    refetchInterval: (q) => (jobRunning(q.state.data) ? POLL_MS : false),
  });

export const useResumes = () => useQuery({ queryKey: keys.resumes, queryFn: resumesApi.list });

/** A resume. Polls while it is still being read, unless `poll` is false. */
export const useResume = (resumeId: string | null, poll = true) =>
  useQuery({
    queryKey: keys.resume(resumeId ?? ""),
    queryFn: () => resumesApi.get(resumeId ?? ""),
    enabled: Boolean(resumeId),
    refetchInterval: (q) => (poll && q.state.data?.status === "pending" ? POLL_MS : false),
  });

export const useResumeTask = (resumeId: string | null, taskId: string | null) =>
  useQuery({
    queryKey: keys.resumeTask(resumeId ?? "", taskId ?? ""),
    queryFn: () => resumesApi.job(resumeId ?? "", taskId ?? ""),
    enabled: Boolean(resumeId && taskId),
    refetchInterval: (q) => (jobRunning(q.state.data) ? POLL_MS : false),
  });

export const useGapAnalysis = (jobId: string) =>
  useQuery({
    queryKey: keys.gap(jobId),
    queryFn: () => gapApi.get(jobId),
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });

export const useJobSessions = (jobId: string) =>
  useQuery({ queryKey: keys.jobSessions(jobId), queryFn: () => sessionsApi.listForJob(jobId) });

export const useProgress = (jobId: string) =>
  useQuery({ queryKey: keys.progress(jobId), queryFn: () => debriefApi.progress(jobId) });

export const useSession = (sessionId: string) =>
  useQuery({
    queryKey: keys.session(sessionId),
    queryFn: () => sessionsApi.get(sessionId),
    // A new session waits for its interviewer brief (built by the worker) before it can start.
    refetchInterval: (q) => (q.state.data?.status === "created" && !q.state.data.brief_ready ? POLL_MS : false),
  });

export const useDebrief = (sessionId: string) =>
  useQuery({
    queryKey: keys.debrief(sessionId),
    queryFn: () => debriefApi.get(sessionId),
    refetchInterval: (q) => (q.state.data?.status === "scoring" ? POLL_MS : false),
  });
