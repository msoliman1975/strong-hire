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

// jsdom has <dialog> but not showModal() and close(): open and close it by its attribute.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
}
