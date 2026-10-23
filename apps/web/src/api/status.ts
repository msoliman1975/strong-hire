/**
 * Ops controls as the candidate app sees them (OC-1 to OC-4): the site banner, and whether
 * sign-ups and new sessions are open. GET /status is public.
 *
 * When a control is on, the API refuses with HTTP 503 and detail.code `signups_paused`,
 * `sessions_paused` or `spend_cap_reached`; `isPausedError` spots those.
 */
import { useQuery } from "@tanstack/react-query";

import { ApiError, apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

export type SiteStatus = components["schemas"]["SiteStatus"];
export type SiteBannerInfo = NonNullable<SiteStatus["banner"]>;

export const PAUSED_CODES = ["signups_paused", "sessions_paused", "spend_cap_reached"] as const;

export const SESSIONS_UNAVAILABLE = "New interviews are temporarily unavailable. Please try again in a little while.";

export const statusApi = {
  get: async () => unwrap(await apiClient.GET("/status")) as SiteStatus,
};

export const statusKey = ["status"] as const;

export const useSiteStatus = () =>
  useQuery({ queryKey: statusKey, queryFn: statusApi.get, staleTime: 30_000, refetchInterval: 120_000 });

/** True for the API's "paused" refusals (OC-1 to OC-3). */
export function isPausedError(err: unknown): err is ApiError {
  return (
    err instanceof ApiError && err.status === 503 && (PAUSED_CODES as readonly string[]).includes(err.code ?? "")
  );
}
