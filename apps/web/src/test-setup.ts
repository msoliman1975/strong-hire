import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { mockStore, server } from "./mocks/node";
import { resetMockSuggestions } from "./mocks/suggestionHandlers";
import { setFirstRunGate } from "./pages/start/gate";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
// U05: the first-run routing is off unless a test turns it on (onboarding tests do).
beforeEach(() => setFirstRunGate(false));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  mockStore.reset();
  resetMockSuggestions();
});
afterAll(() => server.close());
