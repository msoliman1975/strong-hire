/**
 * Starts MSW in the browser during development. main.tsx imports this only when
 * import.meta.env.DEV is true, so production builds contain no mocks.
 *
 * VITE_API_MOCKS:
 *   planned (default)  mock only endpoints the API does not have yet; sign-in, job targets and
 *                      resumes use the real API (the mock keeps a copy for the planned endpoints)
 *   all                mock everything, including sign-in (no API needed; used by Playwright)
 *   off                no mocks
 */
import { setupWorker } from "msw/browser";

import { createStore } from "./db";
import { authHandlers, inputHandlers, inputMirrorHandlers, plannedHandlers } from "./handlers";

export type MockMode = "planned" | "all" | "off";

export function mockMode(): MockMode {
  const value = import.meta.env.VITE_API_MOCKS;
  return value === "all" || value === "off" ? value : "planned";
}

export async function startMocks(mode: MockMode): Promise<void> {
  if (mode === "off") return;
  const store = createStore({ persist: true, delayMs: 800 });
  const handlers =
    mode === "all"
      ? [...inputHandlers(store), ...plannedHandlers(store), ...authHandlers(store)]
      : [...inputMirrorHandlers(store), ...plannedHandlers(store)];
  await setupWorker(...handlers).start({ onUnhandledFrame: "bypass", quiet: true });
  // A way to start over during a click-through: run `strongHireMocks.reset()` in the console.
  (globalThis as { strongHireMocks?: unknown }).strongHireMocks = { reset: () => store.reset(), mode };
}
