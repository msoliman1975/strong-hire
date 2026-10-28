/** MSW for Vitest. Every request is mocked. */
import { setupServer } from "msw/node";

import { adminHandlers } from "./adminHandlers";
import { alertsHandlers } from "./alertsHandlers";
import { controlsHandlers } from "./controlsHandlers";
import { contentHandlers } from "./contentHandlers";
import { createStore } from "./db";
import { authHandlers } from "./handlers";
import { opsHandlers } from "./opsHandlers";
import { simHandlers } from "./simHandlers";
import { settingsHandlers } from "./settingsHandlers";
import { usersHandlers } from "./usersHandlers";
import { waitlistHandlers } from "./waitlistHandlers";
import { part1Handlers } from "./part1Handlers";
import { part2Handlers } from "./part2Handlers";

export const mockStore = createStore({ persist: false });
export const server = setupServer(...authHandlers(mockStore), ...adminHandlers(mockStore), ...alertsHandlers(mockStore), ...controlsHandlers(mockStore), ...usersHandlers(mockStore), ...opsHandlers(mockStore), ...simHandlers(mockStore), ...contentHandlers(mockStore), ...settingsHandlers(mockStore), ...waitlistHandlers(mockStore), ...part1Handlers(mockStore), ...part2Handlers(mockStore));
