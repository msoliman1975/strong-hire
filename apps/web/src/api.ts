export type Health = {
  status: "ok" | "degraded";
  version: string;
  model_profile: string;
  checks: Record<string, string>;
};

/** Calls the API through the Vite proxy (/api -> API service). */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const resp = await fetch("/api/health", { signal });
  if (!resp.ok && resp.status !== 503) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return (await resp.json()) as Health;
}
