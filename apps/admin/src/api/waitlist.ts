/** The waitlist (L04): counts, entries and the CSV download. Read-only. */
import { useQuery } from "@tanstack/react-query";

import { API_BASE, apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

export type AdminWaitlist = components["schemas"]["AdminWaitlist"];
export type AdminWaitlistEntry = components["schemas"]["AdminWaitlistEntry"];

export const waitlistApi = {
  list: async () => unwrap(await apiClient.GET("/admin/waitlist")),
  /** A plain link: the browser sends the admin session cookie with it. */
  csvUrl: `${API_BASE}/admin/waitlist.csv`,
};

export const useWaitlist = () => useQuery({ queryKey: ["admin", "waitlist"], queryFn: waitlistApi.list });
