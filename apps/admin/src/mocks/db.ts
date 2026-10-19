/**
 * In-memory state behind the mock API, for tests and `VITE_API_MOCKS=all`. In the browser it is
 * saved to localStorage so a page reload keeps it. This file is mock-only and never ships.
 */
import type { AuthUser, SessionRecord, Usage } from "../api/types";

/** A row of admin_users (AA-1). */
export interface MockAdmin {
  id: string;
  email: string;
  added_by: string | null;
  added_at: string;
  disabled_at: string | null;
}

/** A row of admin_sessions (AA-3). */
export interface MockAdminSession {
  id: string;
  email: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string | null;
  user_agent: string | null;
  revoked: boolean;
}

export interface MockDb {
  /** The admin session of this browser (the sh_admin cookie), or null when signed out. */
  signedIn: string | null;
  admins: MockAdmin[];
  adminSessions: MockAdminSession[];
  /** Candidate accounts, listed on the Users page. */
  users: Record<string, AuthUser>;
  /** Mock passwords by email (AC-4); admins sign in with their account's password. */
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

/** The admin every mock database starts with, like an ADMIN_EMAILS seed. */
export const MOCK_ADMIN_EMAIL = "admin@example.com";

export function mockAdmin(email: string, n = 1, addedBy: string | null = "ADMIN_EMAILS"): MockAdmin {
  return {
    id: `00000000-0000-4000-8000-0000000000e${n}`,
    email,
    added_by: addedBy,
    added_at: "2026-10-01T09:00:00Z",
    disabled_at: null,
  };
}

export function emptyDb(): MockDb {
  return {
    signedIn: null,
    admins: [mockAdmin(MOCK_ADMIN_EMAIL)],
    adminSessions: [],
    users: {},
    passwords: {},
    sessions: [],
    usage: { ...FREE_USAGE },
  };
}

const STORAGE_KEY = "strong-hire-admin-mock-db-v2";

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
