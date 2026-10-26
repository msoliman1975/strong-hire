/** MSW for Vitest. Every request is mocked, with no processing delay. */
import { setupServer } from "msw/node";

import { customHandlers } from "./custom";
import { createStore } from "./db";
import { accountHandlers, authHandlers, inputHandlers, sessionHandlers, scoringHandlers } from "./handlers";
import { questionHandlers } from "./questionHandlers";
import { waitlistHandlers } from "./waitlistHandlers";

export const mockStore = createStore({ persist: false, delayMs: 0 });
export const server = setupServer(
  ...inputHandlers(mockStore),
  ...sessionHandlers(mockStore),
  ...scoringHandlers(mockStore),
  ...authHandlers(mockStore),
  ...accountHandlers(mockStore),
  ...customHandlers(mockStore),
  ...questionHandlers(),
  ...waitlistHandlers(),
);
