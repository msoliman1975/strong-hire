/**
 * Feature flags read by the UI (FL-1). `v2_enabled` comes from the public `GET /status`
 * (`SiteStatus.v2_enabled`), through the same query as the site banner. A flag is off while
 * the status loads and when it fails.
 */
import { useSiteStatus } from "../api/status";

export type Feature = "v2_enabled";

const DEFAULTS: Record<Feature, boolean> = {
  v2_enabled: false,
};

let overrides: Partial<Record<Feature, boolean>> = {};

/** Tests and the dev mocks set a flag with this. An override wins over `GET /status`. */
export function setFeatureOverrides(next: Partial<Record<Feature, boolean>>) {
  overrides = next;
}

export function useFeature(feature: Feature): boolean {
  const status = useSiteStatus();
  const override = overrides[feature];
  if (override !== undefined) return override;
  if (status.isError || !status.data) return DEFAULTS[feature];
  return status.data[feature] ?? DEFAULTS[feature];
}
