/**
 * In-memory state behind the mock API, so a click-through behaves like the real app: a job you
 * add shows on the dashboard, the free interview is used once, and so on. In the browser it is
 * saved to localStorage so a page reload keeps it. This file is mock-only and never ships.
 */
import type { SessionRecord } from "../api/sessions";
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

/** A gap analysis as the mock keeps it. The R1 name fields are filled in when it is sent. */
export type MockGap = Omit<GapAnalysisOut, "resume_name" | "resume_deleted" | "job_deleted"> & {
  readyAt: number;
};

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
  gaps: Record<string, MockGap>;
  /** R1: normalized posting text per job target id, for the "saved before" match. */
  jobTexts: Record<string, string>;
  /** R1: SHA-256 of each resume's file or pasted text, by resume id. */
  resumeHashes: Record<string, string>;
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
    jobs: [],
    resumes: [],
    tasks: {},
    gaps: {},
    jobTexts: {},
    resumeHashes: {},
    sessions: [],
    debriefReadyAt: {},
    usage: { ...FREE_USAGE },
    exports: {},
    exitSurveys: [],
  };
}

/** Version 5: saved job and CV names and soft delete (R1). Older data is dropped. */
const STORAGE_KEY = "strong-hire-mock-db-v5";

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
