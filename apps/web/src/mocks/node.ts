/** MSW for Vitest. Every request is mocked, with no processing delay. */
import { setupServer } from "msw/node";

import { createStore } from "./db";
import { authHandlers, inputHandlers, plannedHandlers } from "./handlers";

export const mockStore = createStore({ persist: false, delayMs: 0 });
export const server = setupServer(
  ...inputHandlers(mockStore),
  ...plannedHandlers(mockStore),
  ...authHandlers(mockStore),
);
