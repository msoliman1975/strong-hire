/** MSW for Vitest. Every request is mocked, with no processing delay. */
import { setupServer } from "msw/node";

import { createStore } from "./db";
import { authHandlers, plannedHandlers } from "./handlers";

export const mockStore = createStore({ persist: false, delayMs: 0 });
export const server = setupServer(...plannedHandlers(mockStore), ...authHandlers(mockStore));
