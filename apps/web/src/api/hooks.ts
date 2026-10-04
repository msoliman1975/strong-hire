import { useQuery } from "@tanstack/react-query";

import { authApi } from "./auth";
import { billingApi, debriefApi, gapApi, jobsApi, resumesApi, sessionsApi } from "./planned";

/** How often to re-check work that runs in the background (extraction, analysis, scoring). */
export const POLL_MS = 1000;

export const keys = {
  me: ["auth", "me"] as const,
  providers: ["auth", "providers"] as const,
  usage: ["billing", "usage"] as const,
  plan: ["billing", "plan"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["jobs", id] as const,
  jobSessions: (id: string) => ["jobs", id, "sessions"] as const,
  gap: (id: string) => ["jobs", id, "gap"] as const,
  progress: (id: string) => ["jobs", id, "progress"] as const,
  resumes: ["resumes"] as const,
  resume: (id: string) => ["resumes", id] as const,
  session: (id: string) => ["sessions", id] as const,
  debrief: (id: string) => ["sessions", id, "debrief"] as const,
};

export const useAuth = () => useQuery({ queryKey: keys.me, queryFn: authApi.me, staleTime: 30_000 });

export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: authApi.providers, staleTime: Infinity });

export const useUsage = (enabled = true) =>
  useQuery({ queryKey: keys.usage, queryFn: billingApi.usage, enabled });

export const usePlan = () => useQuery({ queryKey: keys.plan, queryFn: billingApi.plan });

export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: jobsApi.list });

export const useJob = (jobId: string) =>
  useQuery({
    queryKey: keys.job(jobId),
    queryFn: () => jobsApi.get(jobId),
    refetchInterval: (q) => (q.state.data?.status === "extracting" ? POLL_MS : false),
  });

export const useResumes = () => useQuery({ queryKey: keys.resumes, queryFn: resumesApi.list });

export const useResume = (resumeId: string | null) =>
  useQuery({
    queryKey: keys.resume(resumeId ?? ""),
    queryFn: () => resumesApi.get(resumeId ?? ""),
    enabled: Boolean(resumeId),
    refetchInterval: (q) => (q.state.data?.status === "parsing" ? POLL_MS : false),
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
  useQuery({ queryKey: keys.session(sessionId), queryFn: () => sessionsApi.get(sessionId) });

export const useDebrief = (sessionId: string) =>
  useQuery({
    queryKey: keys.debrief(sessionId),
    queryFn: () => debriefApi.get(sessionId),
    refetchInterval: (q) => (q.state.data?.status === "scoring" ? POLL_MS : false),
  });
