/**
 * Users and support (AU-1..AU-10): search, user detail, grants, suspend, force sign-out and
 * resend sign-in link. Writes send `X-Admin-Request: 1` and a reason (AA-5, AA-6).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

export type AdminUser = S["AdminUser"];
export type AdminUserPage = S["AdminUserPage"];
export type AdminUserDetail = S["AdminUserDetail"];
export type AdminGrant = S["AdminGrant"];
export type GrantKind = S["GrantKind"];
export type AdminActionOut = S["AdminActionOut"];

export interface UserFilters {
  q?: string;
  plan?: "free" | "paid";
  status?: "active" | "suspended";
  signed_up_from?: string;
  signed_up_to?: string;
  last_sign_in_from?: string;
  last_sign_in_to?: string;
  page?: number;
  page_size?: number;
}

export interface GrantInput {
  kind: GrantKind;
  amount: number;
  expires_at?: string | null;
  reason: string;
}

const WRITE = { "X-Admin-Request": "1" } as const;
const path = (userId: string) => ({ path: { user_id: userId } });

export const usersApi = {
  list: async (filters: UserFilters = {}) =>
    unwrap(await apiClient.GET("/admin/users", { params: { query: filters } })),
  detail: async (userId: string) =>
    unwrap(await apiClient.GET("/admin/users/{user_id}", { params: path(userId) })),
  grant: async (userId: string, body: GrantInput) =>
    unwrap(await apiClient.POST("/admin/users/{user_id}/grants", { params: path(userId), body, headers: WRITE })),
  revokeGrant: async (userId: string, grantId: string, reason: string) =>
    unwrap(
      await apiClient.DELETE("/admin/users/{user_id}/grants/{grant_id}", {
        params: { path: { user_id: userId, grant_id: grantId } },
        body: { reason },
        headers: WRITE,
      }),
    ),
  suspend: async (userId: string, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/users/{user_id}/suspend", { params: path(userId), body: { reason }, headers: WRITE }),
    ),
  unsuspend: async (userId: string, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/users/{user_id}/unsuspend", { params: path(userId), body: { reason }, headers: WRITE }),
    ),
  signOut: async (userId: string, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/users/{user_id}/signout", { params: path(userId), body: { reason }, headers: WRITE }),
    ),
  resendLink: async (userId: string, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/users/{user_id}/resend-link", {
        params: path(userId),
        body: { reason },
        headers: WRITE,
      }),
    ),
};

export const userKeys = {
  all: ["admin", "users"] as const,
  list: (filters: UserFilters) => ["admin", "users", "list", filters] as const,
  detail: (id: string) => ["admin", "users", "detail", id] as const,
};

export const useUserList = (filters: UserFilters) =>
  useQuery({
    queryKey: userKeys.list(filters),
    queryFn: () => usersApi.list(filters),
    placeholderData: keepPreviousData,
  });

export const useUserDetail = (userId: string) =>
  useQuery({ queryKey: userKeys.detail(userId), queryFn: () => usersApi.detail(userId) });

/** Runs one admin action (a closure over usersApi) and refreshes every users query after. */
export function useUserAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: userKeys.all }),
  });
}
