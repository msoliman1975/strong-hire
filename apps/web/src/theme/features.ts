/**
 * Feature flags read by the UI. Until C1 adds the runtime setting `v2_enabled` to the API, every
 * flag is off. C1 replaces the body of `useFeature` with a read from its settings endpoint;
 * callers keep the same signature.
 */
export type Feature = "v2_enabled";

const DEFAULTS: Record<Feature, boolean> = {
  v2_enabled: false,
};

let overrides: Partial<Record<Feature, boolean>> = {};

/** Tests and the dev mocks set a flag with this. */
export function setFeatureOverrides(next: Partial<Record<Feature, boolean>>) {
  overrides = next;
}

export function useFeature(feature: Feature): boolean {
  return overrides[feature] ?? DEFAULTS[feature];
}
