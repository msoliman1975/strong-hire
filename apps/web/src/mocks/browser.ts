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

import { acceptedIssuesHandlers } from "./acceptedIssuesHandlers";
import { interviewHandlers } from "./interviewHandlers";
import { resumeHandlers } from "./resumeHandlers";
import { coachHandlers } from "./coachHandlers";
import { coachVoiceHandlers } from "./coachVoiceHandlers";
import { customHandlers } from "./custom";
import { createStore } from "./db";
import { accountHandlers, authHandlers, inputHandlers, scoringHandlers, sessionHandlers } from "./handlers";
import { planHandlers } from "./planHandlers";
import { storyFitHandlers } from "./storyFitHandlers";
import { questionHandlers } from "./questionHandlers";
import { readinessHandlers } from "./readinessHandlers";
import { storyHandlers } from "./storyHandlers";
import { suggestionHandlers } from "./suggestionHandlers";
import { transcriptHandlers } from "./transcriptHandlers";
import { waitlistHandlers } from "./waitlistHandlers";

export type MockMode = "all" | "off";

export function mockMode(): MockMode {
  return import.meta.env.VITE_API_MOCKS === "all" ? "all" : "off";
}

export async function startMocks(mode: MockMode): Promise<void> {
  if (mode === "off") return;
  const store = createStore({ persist: true, delayMs: 800 });
  const handlers = [
    ...inputHandlers(store),
    ...acceptedIssuesHandlers(store),
    ...resumeHandlers(store),
    ...interviewHandlers(store),
    ...sessionHandlers(store),
    ...scoringHandlers(store),
    ...authHandlers(store),
    ...accountHandlers(store),
    ...customHandlers(store),
    ...planHandlers(store),
    ...storyFitHandlers(),
    ...readinessHandlers(),
    ...questionHandlers(),
    ...storyHandlers(),
    ...suggestionHandlers(),
    ...waitlistHandlers(),
    ...coachVoiceHandlers(),
    ...coachHandlers(store),
    ...transcriptHandlers(),
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
