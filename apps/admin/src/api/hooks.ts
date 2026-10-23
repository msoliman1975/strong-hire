import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authApi } from "./auth";

export const keys = {
  me: ["auth", "me"] as const,
  providers: ["auth", "providers"] as const,
};

/** The signed-in admin (GET /admin/me), or null when signed out. */
export const useAuth = () => useQuery({ queryKey: keys.me, queryFn: authApi.me, staleTime: 30_000 });

export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: authApi.providers, staleTime: Infinity });

/** Signs out (revokes the admin session) and forgets every cached admin answer. */
export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData(keys.me, null);
    },
  });
}
