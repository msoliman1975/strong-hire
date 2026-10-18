/**
 * Alerts (AL-1, AL-4, AL-6): rules with their live state, the metric catalog, mute, test alert,
 * and the history. Writes send `X-Admin-Request: 1` and a reason (AA-5, AA-6).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

export type AlertRule = S["AlertRuleOut"];
export type AlertEvent = S["AlertEventOut"];
export type AlertMetric = S["AlertMetric"];
export type AlertTestResult = S["AlertTestOut"];
export type AlertRuleCreate = S["AlertRuleCreateIn"];
export type AlertRulePatch = S["AlertRulePatchIn"];
export type AlertEventKind = S["AlertEventKind"];
export type AlertState = S["AlertState"];

export interface AlertEventFilters {
  rule_id?: string;
  kind?: AlertEventKind;
  since?: string;
}

const WRITE = { headers: { "X-Admin-Request": "1" } };

const path = (ruleId: string) => ({ params: { path: { rule_id: ruleId } } });

export const alertsApi = {
  metrics: async () => unwrap(await apiClient.GET("/admin/alerts/metrics")),
  rules: async () => unwrap(await apiClient.GET("/admin/alerts/rules")),
  events: async (filters: AlertEventFilters = {}) =>
    unwrap(await apiClient.GET("/admin/alerts/events", { params: { query: filters } })),
  create: async (body: AlertRuleCreate) =>
    unwrap(await apiClient.POST("/admin/alerts/rules", { body, ...WRITE })),
  update: async (ruleId: string, body: AlertRulePatch) =>
    unwrap(await apiClient.PATCH("/admin/alerts/rules/{rule_id}", { ...path(ruleId), body, ...WRITE })),
  remove: async (ruleId: string, reason: string) => {
    const result = await apiClient.DELETE("/admin/alerts/rules/{rule_id}", {
      ...path(ruleId),
      body: { reason },
      ...WRITE,
    });
    unwrap(result);
  },
  mute: async (ruleId: string, until: string | null, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/alerts/rules/{rule_id}/mute", { ...path(ruleId), body: { until, reason }, ...WRITE }),
    ),
  test: async (ruleId: string, reason: string) =>
    unwrap(await apiClient.POST("/admin/alerts/rules/{rule_id}/test", { ...path(ruleId), body: { reason }, ...WRITE })),
};

export const alertKeys = {
  all: ["admin", "alerts"] as const,
  rules: ["admin", "alerts", "rules"] as const,
  metrics: ["admin", "alerts", "metrics"] as const,
  events: (filters: AlertEventFilters) => ["admin", "alerts", "events", filters] as const,
};

/** Refreshed every minute, like the engine, so states and the nav badge stay current. */
export const useAlertRules = () =>
  useQuery({ queryKey: alertKeys.rules, queryFn: alertsApi.rules, refetchInterval: 60_000 });

export const useAlertMetrics = () =>
  useQuery({ queryKey: alertKeys.metrics, queryFn: alertsApi.metrics, staleTime: Infinity });

export const useAlertEvents = (filters: AlertEventFilters) =>
  useQuery({ queryKey: alertKeys.events(filters), queryFn: () => alertsApi.events(filters) });

/** A write on the alerts area; refreshes rules and history when it succeeds. */
export function useAlertWrite<A, R>(fn: (args: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: alertKeys.all }),
  });
}
