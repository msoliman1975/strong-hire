/**
 * In-memory state behind the mock API, so a click-through behaves like the real app: a job you
 * add shows on the dashboard, the free interview is used once, and so on. In the browser it is
 * saved to localStorage so a page reload keeps it. This file is mock-only and never ships.
 */
import type { AuthUser } from "../api/types";
import type {
  ExportJob,
  GapAnalysisResult,
  JobTarget,
  ResumeRecord,
  SessionRecord,
  Usage,
} from "../api/planned";

export interface MockAuth {
  status: "signed_out" | "needs_signup" | "signed_in";
  email: string | null;
  userEmail: string | null;
}

export interface MockDb {
  auth: MockAuth;
  users: Record<string, AuthUser>;
  jobs: JobTarget[];
  /** Job id -> time the extraction finishes. */
  jobReadyAt: Record<string, number>;
  resumes: ResumeRecord[];
  resumeReadyAt: Record<string, number>;
  gaps: Record<string, GapAnalysisResult & { readyAt: number }>;
  sessions: SessionRecord[];
  debriefReadyAt: Record<string, number>;
  usage: Usage;
  exports: Record<string, ExportJob & { readyAt: number }>;
}

export const FREE_USAGE: Usage = {
  plan: "free",
  minutes_used: 0,
  minutes_cap: 0,
  period_end: null,
  free_interview_available: true,
};

export function emptyDb(): MockDb {
  return {
    auth: { status: "signed_out", email: null, userEmail: null },
    users: {},
    jobs: [],
    jobReadyAt: {},
    resumes: [],
    resumeReadyAt: {},
    gaps: {},
    sessions: [],
    debriefReadyAt: {},
    usage: { ...FREE_USAGE },
    exports: {},
  };
}

const STORAGE_KEY = "strong-hire-mock-db";

export interface MockStore {
  db: MockDb;
  save(): void;
  reset(): void;
  /** Simulated processing time for extraction, gap analysis and scoring. */
  delayMs: number;
}

export function createStore(opts: { persist: boolean; delayMs: number }): MockStore {
  const load = (): MockDb => {
    if (!opts.persist) return emptyDb();
    try {
      const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
      return raw ? { ...emptyDb(), ...(JSON.parse(raw) as Partial<MockDb>) } : emptyDb();
    } catch {
      return emptyDb();
    }
  };
  const store: MockStore = {
    db: load(),
    delayMs: opts.delayMs,
    save() {
      if (!opts.persist) return;
      try {
        globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(store.db));
      } catch {
        // Storage can be full or blocked; the mock still works for this page load.
      }
    },
    reset() {
      store.db = emptyDb();
      store.save();
    },
  };
  return store;
}

/** UUIDs, like the real API (ProgressSnapshot ids are UUIDs in the contract). */
export function newId(): string {
  return globalThis.crypto.randomUUID();
}
