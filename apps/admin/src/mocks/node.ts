/** MSW for Vitest. Every request is mocked. */
import { setupServer } from "msw/node";

import { adminHandlers } from "./adminHandlers";
import { alertsHandlers } from "./alertsHandlers";
import { controlsHandlers } from "./controlsHandlers";
import { createStore } from "./db";
import { authHandlers } from "./handlers";
import { opsHandlers } from "./opsHandlers";
import { simHandlers } from "./simHandlers";
import { usersHandlers } from "./usersHandlers";

export const mockStore = createStore({ persist: false });
export const server = setupServer(...authHandlers(mockStore), ...adminHandlers(mockStore), ...alertsHandlers(mockStore), ...controlsHandlers(mockStore), ...usersHandlers(mockStore), ...opsHandlers(mockStore), ...simHandlers(mockStore));
