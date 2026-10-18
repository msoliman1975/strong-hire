import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authApi } from "./auth";
import type { AuthState } from "./types";

export const keys = {
  me: ["auth", "me"] as const,
  providers: ["auth", "providers"] as const,
};

export const SIGNED_OUT: AuthState = { status: "signed_out", email: null, user: null };

export const useAuth = () => useQuery({ queryKey: keys.me, queryFn: authApi.me, staleTime: 30_000 });

export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: authApi.providers, staleTime: Infinity });

/** Signs out and forgets every cached admin answer. */
export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData(keys.me, SIGNED_OUT);
    },
  });
}
