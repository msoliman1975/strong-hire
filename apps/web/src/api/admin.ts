/**
 * Admin area (R2): users, interviews with model cost, interview detail with transcript and
 * interviewer traces (only when the user's consent is on), and the audit log. The API answers 404
 * to everyone who is not in ADMIN_EMAILS.
 */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

export type AdminUser = S["AdminUser"];
export type AdminSession = S["AdminSession"];
export type AdminSessionList = S["AdminSessionList"];
export type AdminSessionDetail = S["AdminSessionDetail"];
export type AdminTrace = S["AdminTrace"];
export type AdminAuditEntry = S["AdminAuditEntry"];
export type DailyCost = S["DailyCost"];
export type AuditScope = "admin" | "all";

export interface AdminSessionFilters {
  user_id?: string;
  day_from?: string;
  day_to?: string;
  interview_type?: S["InterviewType"];
}

export const adminApi = {
  users: async () => unwrap(await apiClient.GET("/admin/users")),
  sessions: async (filters: AdminSessionFilters = {}) =>
    unwrap(await apiClient.GET("/admin/sessions", { params: { query: filters } })),
  session: async (sessionId: string) =>
    unwrap(
      await apiClient.GET("/admin/sessions/{session_id}", { params: { path: { session_id: sessionId } } }),
    ),
  audit: async (scope: AuditScope = "admin") =>
    unwrap(await apiClient.GET("/admin/audit", { params: { query: { scope } } })),
};

export const adminKeys = {
  users: ["admin", "users"] as const,
  sessions: (filters: AdminSessionFilters) => ["admin", "sessions", filters] as const,
  session: (id: string) => ["admin", "session", id] as const,
  audit: (scope: AuditScope) => ["admin", "audit", scope] as const,
};

export const useAdminUsers = () => useQuery({ queryKey: adminKeys.users, queryFn: adminApi.users });

export const useAdminSessions = (filters: AdminSessionFilters) =>
  useQuery({ queryKey: adminKeys.sessions(filters), queryFn: () => adminApi.sessions(filters) });

/** Each load of a transcript writes an audit row, so the detail is not refetched on its own. */
export const useAdminSession = (sessionId: string) =>
  useQuery({
    queryKey: adminKeys.session(sessionId),
    queryFn: () => adminApi.session(sessionId),
    staleTime: Infinity,
  });

export const useAdminAudit = (scope: AuditScope) =>
  useQuery({ queryKey: adminKeys.audit(scope), queryFn: () => adminApi.audit(scope) });
