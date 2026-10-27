/** The waitlist (L04): counts, entries, the CSV download and invites to sign up. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";
import { ADMIN_WRITE } from "./settings";

export type AdminWaitlist = components["schemas"]["AdminWaitlist"];
export type AdminWaitlistEntry = components["schemas"]["AdminWaitlistEntry"];
export type InviteResult = components["schemas"]["InviteOut"];

export const waitlistApi = {
  list: async () => unwrap(await apiClient.GET("/admin/waitlist")),
  /** A plain link: the browser sends the admin session cookie with it. */
  csvUrl: `${API_BASE}/admin/waitlist.csv`,
  /** Emails each chosen confirmed entry that sign-ups are open (AA-5, AA-6: a reason). */
  invite: async (body: { ids: string[]; reason: string }) =>
    unwrap(await apiClient.POST("/admin/waitlist/invite", { body, headers: ADMIN_WRITE })),
};

const waitlistKey = ["admin", "waitlist"] as const;

export const useWaitlist = () => useQuery({ queryKey: waitlistKey, queryFn: waitlistApi.list });

export function useInviteWaitlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: waitlistApi.invite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: waitlistKey }),
  });
}
