/**
 * Starts MSW in the browser during development. main.tsx imports this only when
 * import.meta.env.DEV is true, so production builds contain no mocks.
 *
 * VITE_API_MOCKS:
 *   off (default)  no mocks: the web app uses the real API (the Docker stack)
 *   all            mock everything, including sign-in and the voice room (no API needed; used by
 *                  Playwright)
 * The old value "planned" now means off: every endpoint the web app uses exists in the API.
 */
import { setupWorker } from "msw/browser";

import { adminHandlers } from "./adminHandlers";
import { createStore } from "./db";
import { accountHandlers, authHandlers, inputHandlers, scoringHandlers, sessionHandlers } from "./handlers";

export type MockMode = "all" | "off";

export function mockMode(): MockMode {
  return import.meta.env.VITE_API_MOCKS === "all" ? "all" : "off";
}

export async function startMocks(mode: MockMode): Promise<void> {
  if (mode === "off") return;
  const store = createStore({ persist: true, delayMs: 800 });
  const handlers = [
    ...inputHandlers(store),
    ...sessionHandlers(store),
    ...scoringHandlers(store),
    ...authHandlers(store),
    ...accountHandlers(store),
    ...adminHandlers(store),
  ];
  await setupWorker(...handlers).start({
    onUnhandledFrame: "bypass",
    quiet: true,
  });
  // A way to start over during a click-through: run `strongHireMocks.reset()` in the console.
  (globalThis as { strongHireMocks?: unknown }).strongHireMocks = {
    reset: () => store.reset(),
    mode,
  };
}
