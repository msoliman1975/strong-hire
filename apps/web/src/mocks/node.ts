/** MSW for Vitest. Every request is mocked, with no processing delay. */
import { setupServer } from "msw/node";

import { createStore } from "./db";
import { accountHandlers, authHandlers, inputHandlers, sessionHandlers, scoringHandlers } from "./handlers";

export const mockStore = createStore({ persist: false, delayMs: 0 });
export const server = setupServer(
  ...inputHandlers(mockStore),
  ...sessionHandlers(mockStore),
  ...scoringHandlers(mockStore),
  ...authHandlers(mockStore),
  ...accountHandlers(mockStore),
);
