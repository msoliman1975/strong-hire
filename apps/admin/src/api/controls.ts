/**
 * Operations → Controls (OC-1 to OC-6): runtime settings without a redeploy, and the read-only
 * model profile. Writes send `X-Admin-Request: 1` and a reason (AA-5, AA-6).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

export type SettingKey = S["SettingKey"];
export type JobKind = S["JobKind"];
export type SiteBanner = S["SiteBanner"];
export type BannerSeverity = NonNullable<SiteBanner["severity"]>;
/** CU-11: who may run Custom interviews. */
export type CustomAccess = S["CustomInterviewAccess"];
export type RuntimeSettings = DeepRequired<S["RuntimeSettings"]>;
export type OpsSettings = Omit<DeepRequired<S["OpsSettings"]>, "values" | "defaults"> & {
  values: RuntimeSettings;
  defaults: RuntimeSettings;
};
export type ModelProfile = DeepRequired<S["ModelProfileOut"]>;

export const JOB_KINDS: { kind: JobKind; label: string }[] = [
  { kind: "gap_analysis", label: "Gap analysis" },
  { kind: "scoring", label: "Scoring" },
];

export const ADMIN_WRITE_HEADERS = { "X-Admin-Request": "1" };

export const controlsApi = {
  settings: async () => unwrap(await apiClient.GET("/admin/ops/settings")) as OpsSettings,
  models: async () => unwrap(await apiClient.GET("/admin/ops/models")) as ModelProfile,
  set: async (key: SettingKey, value: unknown, reason: string) =>
    unwrap(
      await apiClient.PUT("/admin/ops/settings/{key}", {
        params: { path: { key } },
        body: { value, reason },
        headers: ADMIN_WRITE_HEADERS,
      }),
    ) as OpsSettings,
};

export const controlsKeys = {
  settings: ["admin", "ops", "settings"] as const,
  models: ["admin", "ops", "models"] as const,
};

/** The Shell reads this on every page for its banner, so it is shared and refreshed each minute. */
export const useOpsSettings = () =>
  useQuery({ queryKey: controlsKeys.settings, queryFn: controlsApi.settings, refetchInterval: 60_000 });

export const useOpsModels = () => useQuery({ queryKey: controlsKeys.models, queryFn: controlsApi.models });

export function useSetSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, reason }: { key: SettingKey; value: unknown; reason: string }) =>
      controlsApi.set(key, value, reason),
    onSuccess: (data) => queryClient.setQueryData(controlsKeys.settings, data),
  });
}

/** True when a banner is set and its end time has not passed. */
export function bannerActive(banner: SiteBanner | null | undefined, now = Date.now()): boolean {
  if (!banner) return false;
  return Date.parse(banner.until) > now;
}

/**
 * The controls that are not at their default, in words, for the Shell banner. A banner that has
 * ended and a spend cap that differs from the default are listed too, so nothing changes quietly.
 */
export function activeControls(settings: OpsSettings, now = Date.now()): string[] {
  const v = settings.values;
  const out: string[] = [];
  if (v.signups_paused) out.push("Sign-ups paused");
  if (v.sessions_paused_voice) out.push("Voice sessions paused");
  if (v.sessions_paused_text) out.push("Text sessions paused");
  if (v.daily_spend_cap_usd !== settings.defaults.daily_spend_cap_usd) {
    out.push(`Spend cap $${v.daily_spend_cap_usd.toFixed(2)} (default $${settings.defaults.daily_spend_cap_usd.toFixed(2)})`);
  }
  if (v.daily_spend_cap_usd >= 0 && settings.spend_today_usd >= v.daily_spend_cap_usd) {
    out.push("Spend cap reached: new sessions refused");
  }
  if (bannerActive(v.site_banner, now)) out.push("Site banner shown");
  if (v.custom_interview_access !== settings.defaults.custom_interview_access) {
    out.push(v.custom_interview_access === "paid_only" ? "Custom interviews for paid plans only" : "Custom interviews open to everyone");
  }
  for (const { kind, label } of JOB_KINDS) {
    if (v.jobs_paused.includes(kind)) out.push(`${label} jobs paused`);
  }
  return out;
}
