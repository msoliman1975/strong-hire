/**
 * Overview (AD-2, AO) and Operations (OB-10..OB-14) routes. Reads are plain queries; writes
 * (resolve an error group, retry a job) send `X-Admin-Request: 1` and a reason (AA-5, AA-6).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

export type AdminMetric = S["AdminMetric"];
export type AdminOverview = S["AdminOverview"];
export type FunnelStep = S["FunnelStep"];
export type CostDay = S["CostDay"];
export type CostSlice = S["CostSlice"];
export type OpsHealth = S["OpsHealth"];
export type OpsTile = S["OpsTile"];
export type OpsHostMetric = S["OpsHostMetric"];
export type OpsPoint = S["OpsPoint"];
export type OpsSeries = S["OpsSeries"];
export type OpsPerformance = S["OpsPerformance"];
export type LatencyStat = S["LatencyStat"];
export type LatencySeries = S["LatencySeries"];
export type OpsErrorGroup = S["OpsErrorGroup"];
export type OpsErrorDetail = S["OpsErrorDetail"];
export type OpsJobs = S["OpsJobs"];
export type OpsJob = S["OpsJob"];
export type OpsRetryOut = S["OpsRetryOut"];
export type OpsSpend = S["OpsSpend"];
export type Heartbeat = S["Heartbeat"];

export type RangeKey = "24h" | "7d" | "30d" | "90d";
export const RANGES: { key: RangeKey; label: string }[] = [
  { key: "24h", label: "24 hours" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
];
export type ErrorStatusFilter = "open" | "resolved" | "all";
export type JobKind = "gap_analysis" | "scoring";

const WRITE_HEADERS = { "X-Admin-Request": "1" };

export const opsApi = {
  overview: async (range: RangeKey) =>
    unwrap(await apiClient.GET("/admin/overview", { params: { query: { range } } })),
  health: async () => unwrap(await apiClient.GET("/admin/ops/health")),
  performance: async (range: RangeKey) =>
    unwrap(await apiClient.GET("/admin/ops/performance", { params: { query: { range } } })),
  errors: async (status: ErrorStatusFilter) =>
    unwrap(await apiClient.GET("/admin/ops/errors", { params: { query: { status } } })),
  error: async (id: string) =>
    unwrap(await apiClient.GET("/admin/ops/errors/{group_id}", { params: { path: { group_id: id } } })),
  updateError: async (id: string, status: "open" | "resolved", reason: string) =>
    unwrap(
      await apiClient.PATCH("/admin/ops/errors/{group_id}", {
        params: { path: { group_id: id } },
        body: { status, reason },
        headers: WRITE_HEADERS,
      }),
    ),
  jobs: async () => unwrap(await apiClient.GET("/admin/ops/jobs")),
  retry: async (kind: JobKind, id: string, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/ops/jobs/{kind}/{job_id}/retry", {
        params: { path: { kind, job_id: id } },
        body: { reason },
        headers: WRITE_HEADERS,
      }),
    ),
  spend: async () => unwrap(await apiClient.GET("/admin/ops/spend")),
};

export const opsKeys = {
  overview: (range: RangeKey) => ["admin", "overview", range] as const,
  health: ["admin", "ops", "health"] as const,
  performance: (range: RangeKey) => ["admin", "ops", "performance", range] as const,
  errors: (status: ErrorStatusFilter) => ["admin", "ops", "errors", status] as const,
  error: (id: string) => ["admin", "ops", "error", id] as const,
  jobs: ["admin", "ops", "jobs"] as const,
  spend: ["admin", "ops", "spend"] as const,
};

/** Live pages refresh every 30 s while open. */
const LIVE = 30_000;

export const useOverview = (range: RangeKey) =>
  useQuery({ queryKey: opsKeys.overview(range), queryFn: () => opsApi.overview(range) });

export const useOpsHealth = () =>
  useQuery({ queryKey: opsKeys.health, queryFn: opsApi.health, refetchInterval: LIVE });

export const useOpsPerformance = (range: RangeKey) =>
  useQuery({ queryKey: opsKeys.performance(range), queryFn: () => opsApi.performance(range) });

export const useOpsErrors = (status: ErrorStatusFilter) =>
  useQuery({ queryKey: opsKeys.errors(status), queryFn: () => opsApi.errors(status), refetchInterval: LIVE });

export const useOpsError = (id: string | null) =>
  useQuery({
    queryKey: opsKeys.error(id ?? ""),
    queryFn: () => opsApi.error(id ?? ""),
    enabled: id !== null,
  });

export const useOpsJobs = () => useQuery({ queryKey: opsKeys.jobs, queryFn: opsApi.jobs, refetchInterval: LIVE });

export const useOpsSpend = () => useQuery({ queryKey: opsKeys.spend, queryFn: opsApi.spend, refetchInterval: LIVE });

export function useUpdateError() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; status: "open" | "resolved"; reason: string }) =>
      opsApi.updateError(v.id, v.status, v.reason),
    onSuccess: (detail) => {
      qc.setQueryData(opsKeys.error(detail.group.id), detail);
      void qc.invalidateQueries({ queryKey: ["admin", "ops", "errors"] });
    },
  });
}

export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { kind: JobKind; id: string; reason: string }) => opsApi.retry(v.kind, v.id, v.reason),
    onSuccess: () => void qc.invalidateQueries({ queryKey: opsKeys.jobs }),
  });
}
