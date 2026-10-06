/**
 * In-memory state behind the mock API, so a click-through behaves like the real app: a job you
 * add shows on the dashboard, the free interview is used once, and so on. In the browser it is
 * saved to localStorage so a page reload keeps it. This file is mock-only and never ships.
 */
import type { SessionRecord } from "../api/planned";
import type {
  AuthUser,
  ExitSurveyIn,
  ExportJob,
  GapAnalysisOut,
  JobOut,
  JobTargetOut,
  ResumeOut,
  Usage,
} from "../api/types";

/** A mock background job (Arq in the real API): reads a posting or parses a resume. */
export interface MockTask extends JobOut {
  readyAt: number;
  kind: "job_target" | "resume";
  entityId: string;
  /** What the job reports when it finishes. */
  outcome: "extracted" | "needs_paste";
}

export interface MockAuth {
  status: "signed_out" | "needs_signup" | "signed_in";
  email: string | null;
  userEmail: string | null;
}

export interface MockDb {
  auth: MockAuth;
  users: Record<string, AuthUser>;
  jobs: JobTargetOut[];
  resumes: ResumeOut[];
  tasks: Record<string, MockTask>;
  /** The latest gap analysis per job target id. */
  gaps: Record<string, GapAnalysisOut & { readyAt: number }>;
  sessions: SessionRecord[];
  debriefReadyAt: Record<string, number>;
  usage: Usage;
  exports: Record<string, ExportJob & { readyAt: number }>;
  exitSurveys: ExitSurveyIn[];
}

/** The real API's answer for a new user (GET /billing/usage). */
export const FREE_USAGE: Usage = {
  plan: "free",
  status: null,
  minutes_used: 0,
  minutes_cap: 0,
  minutes_left: 0,
  period_start: null,
  period_end: null,
  cancel_at_period_end: false,
  free_interviews_total: 1,
  free_interviews_left: 1,
  can_start_session: true,
  block_code: null,
  has_billing_account: false,
};

export function emptyDb(): MockDb {
  return {
    auth: { status: "signed_out", email: null, userEmail: null },
    users: {},
    jobs: [],
    resumes: [],
    tasks: {},
    gaps: {},
    sessions: [],
    debriefReadyAt: {},
    usage: { ...FREE_USAGE },
    exports: {},
    exitSurveys: [],
  };
}

/** Version 4: gap analyses (P6), usage and exports (P9) use the real shapes. Older data is dropped. */
const STORAGE_KEY = "strong-hire-mock-db-v4";

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
