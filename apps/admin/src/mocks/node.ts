/** MSW for Vitest. Every request is mocked. */
import { setupServer } from "msw/node";

import { adminHandlers } from "./adminHandlers";
import { controlsHandlers } from "./controlsHandlers";
import { createStore } from "./db";
import { authHandlers } from "./handlers";

export const mockStore = createStore({ persist: false });
export const server = setupServer(...authHandlers(mockStore), ...adminHandlers(mockStore), ...controlsHandlers(mockStore));
