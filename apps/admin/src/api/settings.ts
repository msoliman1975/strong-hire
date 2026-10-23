/**
 * Settings (AA-1, AA-8): the admins of the admin app, and my own admin sessions. Writes send
 * `X-Admin-Request: 1` (AA-5); adding or removing an admin takes a reason for the audit log (AA-6).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import { keys } from "./hooks";

export const ADMIN_WRITE = { "X-Admin-Request": "1" } as const;

async function noContent(result: { error?: unknown; response: Response }): Promise<void> {
  if (!result.response.ok) unwrap(result);
}

export const settingsApi = {
  admins: async () => unwrap(await apiClient.GET("/admin/admins")),
  addAdmin: async (body: { email: string; reason: string }) =>
    unwrap(await apiClient.POST("/admin/admins", { body, headers: ADMIN_WRITE })),
  removeAdmin: async ({ id, reason }: { id: string; reason: string }) =>
    unwrap(
      await apiClient.DELETE("/admin/admins/{admin_id}", {
        params: { path: { admin_id: id } },
        body: { reason },
        headers: ADMIN_WRITE,
      }),
    ),
  mySessions: async () => unwrap(await apiClient.GET("/admin/me/sessions")),
  revokeSession: async (id: string) =>
    noContent(
      await apiClient.DELETE("/admin/me/sessions/{session_id}", {
        params: { path: { session_id: id } },
        headers: ADMIN_WRITE,
      }),
    ),
};

export const settingsKeys = {
  admins: ["settings", "admins"] as const,
  mySessions: ["settings", "my-sessions"] as const,
};

export const useAdmins = () => useQuery({ queryKey: settingsKeys.admins, queryFn: settingsApi.admins });

export const useMySessions = () => useQuery({ queryKey: settingsKeys.mySessions, queryFn: settingsApi.mySessions });

export function useAddAdmin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.addAdmin,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.admins }),
  });
}

export function useRemoveAdmin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.removeAdmin,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.admins }),
  });
}

/** Revoking the current session signs this browser out. */
export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string; current: boolean }) => settingsApi.revokeSession(id),
    onSuccess: (_data, { current }) => {
      if (current) {
        queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
        queryClient.setQueryData(keys.me, null);
      } else {
        void queryClient.invalidateQueries({ queryKey: settingsKeys.mySessions });
      }
    },
  });
}
