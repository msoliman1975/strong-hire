/**
 * Simulations (SM-1 to SM-16): AI candidate interviews started from the admin app, the runs list,
 * and the replay of one interview. Writes send `X-Admin-Request: 1` (AA-5) and are audited.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import { ADMIN_WRITE_HEADERS } from "./controls";
import type { components } from "./schema.gen";

type S = components["schemas"];

type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

export type SimOptions = DeepRequired<S["SimOptions"]>;
export type SimRunIn = S["SimRunIn"];
export type SimRun = DeepRequired<S["SimRunOut"]>;
export type SimRunList = DeepRequired<S["SimRunList"]>;
export type SimRunStatus = S["SimRunStatus"];
export type SimQuality = S["Quality"];
export type SimBehavior = S["Behavior"];
export type SimLevel = S["Level"];
export type SimInputs = NonNullable<SimRun["inputs"]>;
export type SessionReplay = DeepRequired<S["SessionReplay"]>;
export type ReplayLine = SessionReplay["lines"][number];
export type ReplayJudge = NonNullable<SessionReplay["judge"]>;
export type ReplayScorecard = NonNullable<SessionReplay["scorecard"]>;

export interface SimRunFilters {
  status?: SimRunStatus;
  channel?: "text" | "voice";
  source?: "admin" | "suite";
}

/** SM-4: the list polls this often while a run is not finished. */
export const POLL_MS = 5_000;

export const ACTIVE_STATUSES: SimRunStatus[] = ["starting", "interviewing", "judging"];
export const FINISHED_STATUSES: SimRunStatus[] = ["done", "failed", "cancelled"];

export const simApi = {
  options: async () => unwrap(await apiClient.GET("/admin/sim/options")) as SimOptions,
  run: async (runId: string) =>
    unwrap(await apiClient.GET("/admin/sim/runs/{run_id}", { params: { path: { run_id: runId } } })) as SimRun,
  runs: async (filters: SimRunFilters = {}) =>
    unwrap(await apiClient.GET("/admin/sim/runs", { params: { query: filters } })) as SimRunList,
  start: async (body: SimRunIn) =>
    unwrap(await apiClient.POST("/admin/sim/runs", { body, headers: ADMIN_WRITE_HEADERS })) as SimRun,
  keep: async (runId: string, keep: boolean) =>
    unwrap(
      await apiClient.PATCH("/admin/sim/runs/{run_id}", {
        params: { path: { run_id: runId } },
        body: { keep },
        headers: ADMIN_WRITE_HEADERS,
      }),
    ) as SimRun,
  remove: async (runId: string, reason: string) =>
    unwrap(
      await apiClient.DELETE("/admin/sim/runs/{run_id}", {
        params: { path: { run_id: runId } },
        body: { reason },
        headers: ADMIN_WRITE_HEADERS,
      }),
    ) as SimRun,
  cancel: async (runId: string, reason?: string) =>
    unwrap(
      await apiClient.POST("/admin/sim/runs/{run_id}/cancel", {
        params: { path: { run_id: runId } },
        body: { reason: reason ?? null },
        headers: ADMIN_WRITE_HEADERS,
      }),
    ) as SimRun,
  replay: async (sessionId: string) =>
    unwrap(
      await apiClient.GET("/admin/sessions/{session_id}/replay", {
        params: { path: { session_id: sessionId } },
      }),
    ) as SessionReplay,
};

export const simKeys = {
  all: ["admin", "sim"] as const,
  options: ["admin", "sim", "options"] as const,
  runs: (filters: SimRunFilters) => ["admin", "sim", "runs", filters] as const,
  replay: (sessionId: string) => ["admin", "sim", "replay", sessionId] as const,
};

export const useSimOptions = () => useQuery({ queryKey: simKeys.options, queryFn: simApi.options });

/** SM-4: polls every 5 s while any admin run is not finished. */
export const useSimRuns = (filters: SimRunFilters = {}) =>
  useQuery({
    queryKey: simKeys.runs(filters),
    queryFn: () => simApi.runs(filters),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.any_unfinished ? POLL_MS : false),
  });

/** Each load is audited, so the replay is not refetched on its own. */
export const useReplay = (sessionId: string) =>
  useQuery({ queryKey: simKeys.replay(sessionId), queryFn: () => simApi.replay(sessionId), staleTime: Infinity });

function useSimWrite<A>(fn: (args: A) => Promise<SimRun>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: simKeys.all }),
  });
}

export const useStartRun = () => useSimWrite((body: SimRunIn) => simApi.start(body));
export const useKeepRun = () => useSimWrite(({ id, keep }: { id: string; keep: boolean }) => simApi.keep(id, keep));
export const useDeleteRun = () =>
  useSimWrite(({ id, reason }: { id: string; reason: string }) => simApi.remove(id, reason));
export const useCancelRun = () =>
  useSimWrite(({ id, reason }: { id: string; reason?: string }) => simApi.cancel(id, reason));

/** SM-17: the app's own limit for a pasted posting or CV. */
export const MAX_PASTED_CHARS = 60_000;

/** SM-21: the form values that start the same run again. Texts are null once deleted. */
export function runAgainValues(run: SimRun): Required<SimRunIn> {
  const s = run.scenario;
  const inputs = run.inputs;
  return {
    persona: s.persona,
    interview_type: s.interview_type as Required<SimRunIn>["interview_type"],
    difficulty: s.difficulty as Required<SimRunIn>["difficulty"],
    mode: s.mode as Required<SimRunIn>["mode"],
    duration_min: s.duration_min as Required<SimRunIn>["duration_min"],
    quality: s.quality as SimQuality,
    behavior: s.behavior as SimBehavior,
    channel: s.channel as Required<SimRunIn>["channel"],
    job_text: inputs?.job_text ?? null,
    cv_text: inputs?.cv_text ?? null,
    level: inputs?.level ?? s.level ?? null,
  };
}

/** SM-9: the color of a response time. */
export type LatencyLevel = "ok" | "slow" | "bad";

export function latencyLevel(ms: number, okMs = 800, slowMs = 1500): LatencyLevel {
  if (ms < okMs) return "ok";
  return ms <= slowMs ? "slow" : "bad";
}

/** SM-10: "mm:ss" (or "m:ss") in judge text, with its position in ms. */
export interface TimeRef {
  text: string;
  ms: number;
}

const MMSS = /\b(\d{1,3}):([0-5]\d)\b/g;

/** Splits text into plain parts and time links, in order. */
export function splitTimes(text: string): (string | TimeRef)[] {
  const out: (string | TimeRef)[] = [];
  let last = 0;
  for (const m of text.matchAll(MMSS)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push({ text: m[0], ms: (Number(m[1]) * 60 + Number(m[2])) * 1000 });
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** The index of the line playing at `ms`: the last line that started at or before it. */
export function lineAt(lines: ReplayLine[], ms: number): number {
  let found = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].start_ms <= ms) found = i;
    else break;
  }
  return found;
}
