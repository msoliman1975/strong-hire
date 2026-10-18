/**
 * In-memory state behind the mock API, for tests and `VITE_API_MOCKS=all`. In the browser it is
 * saved to localStorage so a page reload keeps it. This file is mock-only and never ships.
 */
import type { AuthUser, SessionRecord, Usage } from "../api/types";

export interface MockAuth {
  status: "signed_out" | "needs_signup" | "signed_in";
  email: string | null;
  userEmail: string | null;
}

export interface MockDb {
  auth: MockAuth;
  users: Record<string, AuthUser>;
  /** Mock passwords by email (AC-4). */
  passwords: Record<string, string>;
  sessions: SessionRecord[];
  usage: Usage;
}

/** The real API's answer for a new user (GET /billing/usage), shown on the Users page. */
export const FREE_USAGE: Usage = {
  plan: "free",
  status: null,
  minutes_used: 0,
  minutes_cap: 0,
  minutes_left: 0,
  period_start: null,
  period_end: null,
  cancel_at_period_end: false,
  free_interviews_total: 2,
  free_interviews_left: 2,
  can_start_session: true,
  full_interviews_allowed: false,
  block_code: null,
  has_billing_account: false,
};

export function emptyDb(): MockDb {
  return {
    auth: { status: "signed_out", email: null, userEmail: null },
    users: {},
    passwords: {},
    sessions: [],
    usage: { ...FREE_USAGE },
  };
}

const STORAGE_KEY = "strong-hire-admin-mock-db-v1";

export interface MockStore {
  db: MockDb;
  save(): void;
  reset(): void;
}

export function createStore(opts: { persist: boolean; seed?: (db: MockDb) => void }): MockStore {
  const fresh = (): MockDb => {
    const db = emptyDb();
    opts.seed?.(db);
    return db;
  };
  const load = (): MockDb => {
    if (!opts.persist) return fresh();
    try {
      const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
      return raw ? { ...emptyDb(), ...(JSON.parse(raw) as Partial<MockDb>) } : fresh();
    } catch {
      return fresh();
    }
  };
  const store: MockStore = {
    db: load(),
    save() {
      if (!opts.persist) return;
      try {
        globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(store.db));
      } catch {
        // Storage can be full or blocked; the mock still works for this page load.
      }
    },
    reset() {
      store.db = fresh();
      store.save();
    },
  };
  return store;
}

/** UUIDs, like the real API. */
export function newId(): string {
  return globalThis.crypto.randomUUID();
}
