/**
 * Starts MSW in the browser during development. main.tsx imports this only when
 * import.meta.env.DEV is true, so production builds contain no mocks.
 *
 * VITE_API_MOCKS:
 *   off (default)  no mocks: the admin app uses the real API (the Docker stack on port 8700)
 *   all            mock everything, with seeded data; no API needed. Sign in as
 *                  admin@example.com (password "admin-password") or ana@example.com
 *                  ("candidate-password", not an admin).
 */
import { setupWorker } from "msw/browser";

import { adminHandlers } from "./adminHandlers";
import { alertsHandlers } from "./alertsHandlers";
import { controlsHandlers } from "./controlsHandlers";
import { contentHandlers } from "./contentHandlers";
import { createStore, type MockDb } from "./db";
import { authHandlers } from "./handlers";
import { usersHandlers } from "./usersHandlers";
import { opsHandlers } from "./opsHandlers";

export type MockMode = "all" | "off";

export function mockMode(): MockMode {
  return import.meta.env.VITE_API_MOCKS === "all" ? "all" : "off";
}

function seed(db: MockDb): void {
  const user = (email: string, n: number, consent: boolean) => ({
    id: `00000000-0000-4000-8000-0000000000a${n}`,
    org_id: `00000000-0000-4000-8000-0000000000b${n}`,
    email,
    auth_provider: "password" as const,
    training_consent: consent,
    created_at: "2026-10-01T10:00:00Z",
    is_admin: false,
    full_name: null,
    profile_complete: true,
  });
  db.users["ana@example.com"] = user("ana@example.com", 1, true);
  db.users["admin@example.com"] = user("admin@example.com", 9, false);
  db.passwords["ana@example.com"] = "candidate-password";
  db.passwords["admin@example.com"] = "admin-password";
  db.sessions.push({
    id: "00000000-0000-4000-8000-0000000000c1",
    job_target_id: "00000000-0000-4000-8000-0000000000d1",
    resume_id: null,
    config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min: 10, level: "senior" },
    channel: "voice",
    brief_ready: true,
    status: "completed",
    started_at: "2026-10-07T09:00:00Z",
    ended_at: "2026-10-07T09:09:30Z",
    minutes_billed: 10,
    failure_reason: null,
  });
}

export async function startMocks(mode: MockMode): Promise<void> {
  if (mode === "off") return;
  const store = createStore({ persist: true, seed });
  await setupWorker(...authHandlers(store), ...adminHandlers(store), ...alertsHandlers(store), ...controlsHandlers(store), ...usersHandlers(store), ...opsHandlers(store), ...contentHandlers(store)).start({
    onUnhandledFrame: "bypass",
    quiet: true,
  });
  // A way to start over during a click-through: run `strongHireAdminMocks.reset()` in the console.
  (globalThis as { strongHireAdminMocks?: unknown }).strongHireAdminMocks = { reset: () => store.reset(), mode };
}
