/**
 * MSW request handlers.
 *
 * - `inputHandlers` stand in for the real job target, resume and gap analysis endpoints (P2, P6),
 *   with the same paths, status codes and bodies as openapi.json. Tests and
 *   `VITE_API_MOCKS=all` use them.
 * - `sessionHandlers` stand in for the real session endpoints (P7) and the voice join (P10). The
 *   join returns a "mock:" URL, so the live page uses a scripted interviewer (src/session/mockVoice).
 * - `scoringHandlers` stand in for the real debrief and progress endpoints (P8), with the shapes
 *   in openapi.json.
 * - `authHandlers` stand in for the real sign-in routes.
 * - `accountHandlers` stand in for the real billing and account routes (P9), with the same
 *   paths, status codes and bodies as openapi.json.
 *
 * Rules such as "one free interview" live here only to make the mock believable. The real rules
 * belong to the API; the web app only shows what the API returns.
 */
import { delay } from "msw";
import { http, HttpResponse } from "msw/http";

import type { CreateSessionRequest, SessionRecord, VoiceJoin } from "../api/sessions";
import { MOCK_VOICE_URL } from "../session/voice";
import type {
  AuthState,
  CompetencyTrend,
  Debrief,
  ExitSurveyIn,
  ExportJob,
  GapAnalysisOut,
  GapAnalysisStart,
  JobContext,
  JobOut,
  JobPosting,
  JobProgress,
  JobTargetAccepted,
  JobTargetCreate,
  JobTargetMatchIn,
  JobTargetOut,
  JobTargetSummary,
  JobTargetUpdate,
  Profile,
  ProfileIn,
  ProgressSnapshot,
  ReportItem,
  Resume,
  ResumeAccepted,
  ResumeOut,
  Usage,
} from "../api/types";
import { isMockAdmin } from "./adminHandlers";
import { newId, type MockGap, type MockStore, type MockTask } from "./db";
import { gapAnalysis, jobPosting, resume, scorecardFor, sessionPlan } from "./fixtures";

const API = "*/api";

function notFound(what: string) {
  return HttpResponse.json({ detail: `${what} not found` }, { status: 404 });
}

/** Drops the mock-only `readyAt` field before a record goes over the wire. */
function publicView<T extends { readyAt: number }>(record: T): Omit<T, "readyAt"> {
  const copy: Partial<T> = { ...record };
  delete copy.readyAt;
  return copy as Omit<T, "readyAt">;
}

function unauthorized() {
  return HttpResponse.json({ detail: "Sign in first" }, { status: 401 });
}

export function authHandlers(store: MockStore) {
  const state = (): AuthState => {
    const { auth, users } = store.db;
    if (auth.status === "signed_in" && auth.userEmail && users[auth.userEmail]) {
      return { status: "signed_in", email: auth.userEmail, user: users[auth.userEmail] };
    }
    if (auth.status === "needs_signup") return { status: "needs_signup", email: auth.email, user: null };
    return { status: "signed_out", email: null, user: null };
  };

  const signInAs = (rawEmail: string): AuthState => {
    const email = rawEmail.trim().toLowerCase();
    store.db.auth = store.db.users[email]
      ? { status: "signed_in", email, userEmail: email }
      : { status: "needs_signup", email, userEmail: null };
    store.save();
    return state();
  };

  return [
    http.get(`${API}/auth/providers`, () => HttpResponse.json({ google: false, email: true, dev: true })),
    http.get(`${API}/auth/me`, () => HttpResponse.json(state())),
    http.post(`${API}/auth/dev-login`, async ({ request }) => {
      const body = (await request.json()) as { email?: string };
      return HttpResponse.json(signInAs(body.email ?? "dev@example.com"));
    }),
    http.post(`${API}/auth/magic-link`, async ({ request }) => {
      const body = (await request.json()) as { email?: string };
      if (!body.email || !body.email.includes("@")) {
        return HttpResponse.json({ detail: [{ msg: "value is not a valid email address" }] }, { status: 422 });
      }
      return HttpResponse.json({ sent: true, dev_link: null }, { status: 202 });
    }),
    http.post(`${API}/auth/signup`, async ({ request }) => {
      const body = (await request.json()) as {
        age_confirmed: boolean;
        terms_accepted: boolean;
        training_consent?: boolean;
      };
      const { auth } = store.db;
      if (auth.status !== "needs_signup" || !auth.email) return unauthorized();
      if (!body.age_confirmed) return HttpResponse.json({ detail: "You must be 18 or older" }, { status: 422 });
      if (!body.terms_accepted) return HttpResponse.json({ detail: "Accept the terms first" }, { status: 422 });
      store.db.users[auth.email] = {
        id: newId(),
        org_id: newId(),
        email: auth.email,
        auth_provider: "dev",
        training_consent: body.training_consent ?? false,
        created_at: new Date().toISOString(),
        is_admin: isMockAdmin(auth.email),
        full_name: null,
        profile_complete: false,
      };
      store.db.auth = { status: "signed_in", email: auth.email, userEmail: auth.email };
      store.save();
      return HttpResponse.json(state());
    }),
    http.post(`${API}/auth/logout`, () => {
      store.db.auth = { status: "signed_out", email: null, userEmail: null };
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}

// ---------------------------------------------------------------------------- shared mock state

/** Companies the mock "matches" (IN-5). Any other name is generic mode. */
const MOCK_COMPANIES: Record<string, { id: string; slug: string }> = {
  stripe: { id: "00000000-0000-4000-8000-000000000001", slug: "stripe" },
};

function matchCompany(target: JobTargetOut, posting: JobPosting) {
  const company = MOCK_COMPANIES[posting.company_name.trim().toLowerCase()];
  target.company_id = company?.id ?? null;
  target.company_slug = company?.slug ?? null;
  target.generic_mode = !company;
  return { company_id: target.company_id, slug: target.company_slug, method: "mock", generic_mode: !company };
}

const EMPTY_CONTEXT: JobContext = {
  interviewer_name: null,
  interviewer_role: null,
  recruiter_notes: null,
  concerns: null,
};

/** AC-3: the profile of a user who has not saved it yet. */
const EMPTY_PROFILE: Profile = {
  full_name: null,
  years_experience: null,
  target_level: null,
  current_title: null,
  country: null,
  time_zone: null,
  linkedin_url: null,
  complete: false,
};

function safeHost(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** Same rule as the API: LinkedIn cannot be fetched, so it needs pasted text. */
const isPasteOnly = (url: string) =>
  ["linkedin.com", "lnkd.in"].some((h) => safeHost(url) === h || safeHost(url).endsWith(`.${h}`));

/** Same rules as strong_core.library (R1), for the mock. */
const today = () => new Date().toISOString().slice(0, 10);
const normalizeText = (text: string) => text.replace(/\s+/g, " ").trim().toLowerCase();
function normalizeUrl(url: string | null | undefined): string | null {
  if (!url?.trim()) return null;
  try {
    const u = new URL(url.trim());
    const host = u.host.toLowerCase().replace(/^www\./, "");
    return `${u.protocol.toLowerCase()}//${host}${u.pathname.replace(/\/+$/, "")}${u.search}`;
  } catch {
    return null;
  }
}
function defaultJobName(target: JobTargetOut): string {
  const p = target.posting;
  if (p?.title && p.company_name) return `${p.title} at ${p.company_name}`.slice(0, 120);
  const host = target.source_url ? safeHost(target.source_url).replace(/^www\./, "") : "";
  return host || `Job description ${today()}`;
}
function defaultResumeName(file: File | null): string {
  const stem = file ? file.name.replace(/\.[^.]*$/, "").trim() : "";
  return stem ? stem.slice(0, 120) : `CV ${today()}`;
}
async function sha256Of(data: ArrayBuffer | string): Promise<string> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
/** Same check as the API's LibraryRename: trimmed, 1 to 120 characters. */
function renameProblem(name: unknown): string | null {
  const value = typeof name === "string" ? name.replace(/\s+/g, " ").trim() : "";
  if (!value) return "The name cannot be empty.";
  if (value.length > 120) return "Use at most 120 characters.";
  return null;
}
const invalid = (msg: string) => HttpResponse.json({ detail: [{ msg: `Value error, ${msg}` }] }, { status: 422 });

/** A gap analysis as the API sends it, with the R1 name fields. */
function gapView(store: MockStore, gap: MockGap): GapAnalysisOut {
  const resumeRecord = store.db.resumes.find((r) => r.id === gap.resume_id);
  const job = store.db.jobs.find((j) => j.id === gap.job_target_id);
  const resumeDeleted = !resumeRecord || resumeRecord.deleted;
  const jobDeleted = job?.deleted ?? true;
  return {
    ...publicView(gap),
    resume_name: resumeDeleted ? null : resumeRecord.name,
    resume_deleted: resumeDeleted,
    job_deleted: jobDeleted,
    stale: jobDeleted || resumeDeleted ? false : gap.stale,
  };
}

/** Mock only: links to this host act like a job board that blocks reading (outcome needs_paste). */
const isBlockedBoard = (url: string) => safeHost(url).endsWith("blocked.example");

const taskView = (task: MockTask): JobOut => ({
  id: task.id,
  status: task.status,
  result: task.result,
  error: task.error,
});

const pauseFor = (store: MockStore) => (store.delayMs > 0 ? delay(150) : Promise.resolve());

/** Moves time-based mock states forward, as background jobs would. */
function advance(store: MockStore) {
  const d = store.db;
  const now = Date.now();
  for (const task of Object.values(d.tasks)) {
    if (task.status !== "queued" || now < task.readyAt) continue;
    task.status = "complete";
    if (task.kind === "job_target") {
      const target = d.jobs.find((j) => j.id === task.entityId);
      if (!target) continue;
      if (task.outcome === "needs_paste") {
        task.result = { outcome: "needs_paste", reason: "blocked", detail: "This job board blocks automatic reading." };
        continue;
      }
      if (target.deleted) continue;
      const posting: JobPosting = { ...jobPosting, source_url: target.source_url };
      target.status = "extracted";
      target.posting = posting;
      target.level = posting.level;
      target.name = defaultJobName(target);
      task.result = { outcome: "extracted", board: null, company: matchCompany(target, posting) };
    } else {
      const r = d.resumes.find((x) => x.id === task.entityId);
      if (!r || r.deleted) continue;
      r.status = "extracted";
      r.resume = resume;
      task.result = { outcome: "extracted", kind: r.has_file ? "pdf" : "text" };
    }
  }
  for (const gap of Object.values(d.gaps)) {
    if (gap.status === "running" && now >= gap.readyAt) {
      const generic = d.jobs.find((j) => j.id === gap.job_target_id)?.company_id == null;
      gap.status = "ready";
      gap.analysis = gapAnalysis;
      gap.generic_mode = generic;
      gap.profile_version = generic ? null : 1;
      gap.updated_at = new Date(now).toISOString();
    }
  }
  for (const s of d.sessions) {
    if (s.status === "scoring" && now >= (d.debriefReadyAt[s.id] ?? 0)) s.status = "completed";
  }
  for (const e of Object.values(d.exports)) {
    if (e.status === "preparing" && now >= e.readyAt) {
      e.status = "ready";
      e.download_url = "data:application/json;charset=utf-8,%7B%22mock%22%3Atrue%7D";
    }
  }
  store.save();
}

// ---------------------------------------------------------------------------- P2 inputs

/** Mocks of the real P2 endpoints. Paths, status codes and bodies follow openapi.json. */
export function inputHandlers(store: MockStore) {
  const db = () => store.db;
  const findJob = (id: unknown) => db().jobs.find((j) => j.id === id);
  const findResume = (id: unknown) => db().resumes.find((r) => r.id === id);
  /** LB-2: a job with a gap analysis or a session is archived, not deleted. */
  const jobInUse = (id: string) => Boolean(db().gaps[id]) || db().sessions.some((x) => x.job_target_id === id);

  const enqueue = (kind: MockTask["kind"], entityId: string, outcome: MockTask["outcome"]): MockTask => {
    const prefix = kind === "job_target" ? "jt" : "rs";
    const task: MockTask = {
      id: `${prefix}:${entityId}:${newId().replaceAll("-", "").slice(0, 12)}`,
      status: "queued",
      result: null,
      error: null,
      readyAt: Date.now() + store.delayMs,
      kind,
      entityId,
      outcome,
    };
    db().tasks[task.id] = task;
    return task;
  };

  const getTask = (kind: MockTask["kind"], entityId: string, taskId: string) => {
    advance(store);
    const task = db().tasks[taskId];
    if (!task || task.kind !== kind || task.entityId !== entityId) return notFound("Job");
    return HttpResponse.json(taskView(task));
  };

  return [
    http.post(`${API}/job-targets`, async ({ request }) => {
      await pauseFor(store);
      const body = (await request.json()) as JobTargetCreate;
      const url = body.url ?? null;
      const text = body.text ?? null;
      if (!url && !text) {
        return HttpResponse.json(
          { detail: [{ msg: "Value error, Give the posting text, a URL, or both." }] },
          { status: 422 },
        );
      }
      if (url && !text && isPasteOnly(url)) {
        return HttpResponse.json(
          { detail: { code: "paste_required", reason: "linkedin", message: "Paste the posting text." } },
          { status: 422 },
        );
      }
      const target: JobTargetOut = {
        id: newId(),
        name: null,
        deleted: false,
        status: "pending",
        source_url: url,
        posting: null,
        level: null,
        company_id: null,
        company_slug: null,
        generic_mode: null,
        stage: body.stage ?? null,
        context: { ...EMPTY_CONTEXT, ...body.context },
        created_at: new Date().toISOString(),
        archived_at: null,
      };
      target.name = defaultJobName(target);
      db().jobs.push(target);
      if (text) db().jobTexts[target.id] = normalizeText(text);
      const blocked = url !== null && !text && isBlockedBoard(url);
      const task = enqueue("job_target", target.id, blocked ? "needs_paste" : "extracted");
      store.save();
      const accepted: JobTargetAccepted = { job_target: target, job: taskView(task) };
      return HttpResponse.json(accepted, { status: 202 });
    }),
    http.get(`${API}/job-targets/:jobTargetId`, ({ params }) => {
      advance(store);
      const target = findJob(params.jobTargetId);
      return target ? HttpResponse.json(target) : notFound("Job target");
    }),
    http.post(`${API}/job-targets/match`, async ({ request }) => {
      advance(store);
      const body = (await request.json()) as JobTargetMatchIn;
      const text = body.text?.trim() ? normalizeText(body.text) : null;
      const url = normalizeUrl(body.url);
      const match = [...db().jobs]
        .reverse()
        .find(
          (j) =>
            !j.deleted &&
            ((text !== null && db().jobTexts[j.id] === text) || (url !== null && normalizeUrl(j.source_url) === url)),
        );
      return HttpResponse.json({ job_target: match ?? null });
    }),
    http.patch(`${API}/job-targets/:jobTargetId`, async ({ params, request }) => {
      const target = findJob(params.jobTargetId);
      if (!target || target.deleted) return notFound("Job target");
      const body = (await request.json()) as { name?: unknown };
      const problem = renameProblem(body.name);
      if (problem) return invalid(problem);
      target.name = String(body.name).replace(/\s+/g, " ").trim();
      store.save();
      return HttpResponse.json(target);
    }),
    http.post(`${API}/job-targets/:jobTargetId/archive`, ({ params }) => {
      const target = findJob(params.jobTargetId);
      if (!target || target.deleted) return notFound("Job target");
      target.archived_at ??= new Date().toISOString();
      store.save();
      return HttpResponse.json(target);
    }),
    http.post(`${API}/job-targets/:jobTargetId/restore`, ({ params }) => {
      const target = findJob(params.jobTargetId);
      if (!target || target.deleted) return notFound("Job target");
      target.archived_at = null;
      store.save();
      return HttpResponse.json(target);
    }),
    http.delete(`${API}/job-targets/:jobTargetId`, ({ params }) => {
      const target = findJob(params.jobTargetId);
      if (!target) return notFound("Job target");
      // LB-2, like the API: a job with reports is archived, not deleted.
      if (!target.deleted && jobInUse(target.id)) {
        return HttpResponse.json(
          { detail: "This job description has reports. Archive it instead of deleting it." },
          { status: 409 },
        );
      }
      // Like the API: the content goes.
      Object.assign(target, { deleted: true, name: null, posting: null, source_url: null, context: { ...EMPTY_CONTEXT } });
      delete db().jobTexts[target.id];
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
    http.put(`${API}/job-targets/:jobTargetId`, async ({ params, request }) => {
      const target = findJob(params.jobTargetId);
      if (!target || target.deleted) return notFound("Job target");
      const body = (await request.json()) as JobTargetUpdate;
      const oldCompany = target.posting?.company_name;
      const posting = { ...(body.posting as JobPosting), source_url: target.source_url };
      target.posting = posting;
      target.level = posting.level;
      target.status = "extracted";
      target.stage = body.stage ?? null;
      target.context = { ...EMPTY_CONTEXT, ...body.context };
      let job: JobOut | null = null;
      if (posting.company_name !== oldCompany) {
        // The real API matches the company again in the background; the mock finishes at once.
        const task = enqueue("job_target", target.id, "extracted");
        task.status = "complete";
        task.result = { outcome: "matched", company: matchCompany(target, posting) };
        job = taskView(task);
      }
      store.save();
      const accepted: JobTargetAccepted = { job_target: target, job };
      return HttpResponse.json(accepted);
    }),
    http.get(`${API}/job-targets/:jobTargetId/jobs/:jobId`, ({ params }) =>
      getTask("job_target", String(params.jobTargetId), String(params.jobId)),
    ),

    http.post(`${API}/resumes`, async ({ request }) => {
      await pauseFor(store);
      const form = await request.formData();
      const file = form.get("file");
      const text = form.get("text");
      const hasFile = file instanceof File;
      const hasText = typeof text === "string" && text.trim() !== "";
      if (hasFile === hasText) {
        return HttpResponse.json({ detail: "Send either a file or the resume text." }, { status: 422 });
      }
      if (hasFile && !/\.(pdf|docx|txt|md)$/i.test(file.name)) {
        return HttpResponse.json({ detail: "Use a PDF, DOCX or text file." }, { status: 415 });
      }
      // The worker stores the file when it runs, so has_file starts false, as in the API.
      const record: ResumeOut = {
        id: newId(),
        name: defaultResumeName(hasFile ? file : null),
        deleted: false,
        status: "pending",
        has_file: false,
        resume: null,
        confirmed_at: null,
        uploaded_at: new Date().toISOString(),
      };
      db().resumes.push(record);
      db().resumeHashes[record.id] = await sha256Of(hasFile ? await file.arrayBuffer() : String(text));
      const task = enqueue("resume", record.id, "extracted");
      store.save();
      const accepted: ResumeAccepted = { resume: record, job: taskView(task) };
      return HttpResponse.json(accepted, { status: 202 });
    }),
    http.get(`${API}/resumes/:resumeId`, ({ params }) => {
      advance(store);
      const r = findResume(params.resumeId);
      return r ? HttpResponse.json(r) : notFound("Resume");
    }),
    http.post(`${API}/resumes/match`, async ({ request }) => {
      const body = (await request.json()) as { sha256?: string };
      if (!body.sha256 || !/^[0-9a-f]{64}$/.test(body.sha256)) return invalid("sha256 must be 64 hex characters");
      const match = [...db().resumes].reverse().find((r) => !r.deleted && db().resumeHashes[r.id] === body.sha256);
      return HttpResponse.json({ resume: match ?? null });
    }),
    http.patch(`${API}/resumes/:resumeId`, async ({ params, request }) => {
      const r = findResume(params.resumeId);
      if (!r || r.deleted) return notFound("Resume");
      const body = (await request.json()) as { name?: unknown };
      const problem = renameProblem(body.name);
      if (problem) return invalid(problem);
      r.name = String(body.name).replace(/\s+/g, " ").trim();
      store.save();
      return HttpResponse.json(r);
    }),
    http.delete(`${API}/resumes/:resumeId`, ({ params }) => {
      const r = findResume(params.resumeId);
      if (!r) return notFound("Resume");
      Object.assign(r, { deleted: true, name: null, resume: null, has_file: false, confirmed_at: null });
      delete db().resumeHashes[r.id];
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
    http.put(`${API}/resumes/:resumeId`, async ({ params, request }) => {
      const r = findResume(params.resumeId);
      if (!r || r.deleted) return notFound("Resume");
      if (r.status !== "extracted") {
        return HttpResponse.json({ detail: "The resume is still being read. Try again in a minute." }, { status: 409 });
      }
      r.resume = ((await request.json()) as { resume: Resume }).resume;
      r.confirmed_at = new Date().toISOString();
      store.save();
      return HttpResponse.json(r);
    }),
    http.get(`${API}/resumes/:resumeId/jobs/:jobId`, ({ params }) =>
      getTask("resume", String(params.resumeId), String(params.jobId)),
    ),

    // ------------------------------------------------------------ lists (P6)
    http.get(`${API}/job-targets`, ({ request }) => {
      advance(store);
      const withArchived = new URL(request.url).searchParams.get("include_archived") === "true";
      const live = db().jobs.filter((j) => !j.deleted && (withArchived || !j.archived_at));
      const summaries: JobTargetSummary[] = [...live].reverse().map((target) => {
        const sessions = db().sessions.filter((x) => x.job_target_id === target.id);
        const gap = db().gaps[target.id];
        return {
          job_target: target,
          match_score: gap?.analysis?.match_score ?? null,
          gap_status: gap?.status ?? null,
          sessions_count: sessions.length,
          last_session_at: sessions.at(-1)?.started_at ?? null,
          in_use: jobInUse(target.id),
        };
      });
      return HttpResponse.json(summaries);
    }),
    http.get(`${API}/resumes`, () => {
      advance(store);
      return HttpResponse.json([...db().resumes].filter((r) => !r.deleted).reverse());
    }),

    // ------------------------------------------------------------ gap analysis (P6)
    http.post(`${API}/job-targets/:jobId/gap-analysis`, async ({ params, request }) => {
      const job = findJob(params.jobId);
      if (!job || job.deleted) return notFound("Job target");
      const body = (await request.json()) as GapAnalysisStart;
      const resumeId = body.resume_id ?? db().gaps[job.id]?.resume_id;
      if (!resumeId) return HttpResponse.json({ detail: "Choose a resume first." }, { status: 422 });
      const r = findResume(resumeId);
      if (!r || r.deleted) return notFound("Resume");
      const current = db().gaps[job.id];
      // R1: the same saved job and CV picked again get the ready analysis back.
      if (body.reuse_ready && current?.status === "ready" && current.resume_id === r.id && !current.stale) {
        return HttpResponse.json(gapView(store, current), { status: 202 });
      }
      if (job.status !== "extracted" || r.status !== "extracted") {
        return HttpResponse.json({ detail: "The job posting or the resume is still being read." }, { status: 409 });
      }
      const gap: MockGap = {
        id: newId(),
        job_target_id: job.id,
        resume_id: r.id,
        status: "running",
        analysis: null,
        error: null,
        generic_mode: null,
        profile_version: null,
        stale: false,
        created_at: new Date().toISOString(),
        updated_at: null,
        readyAt: Date.now() + store.delayMs * 1.5,
      };
      db().gaps[job.id] = gap;
      store.save();
      return HttpResponse.json(gapView(store, gap), { status: 202 });
    }),
    http.get(`${API}/job-targets/:jobId/gap-analysis`, ({ params }) => {
      advance(store);
      const gap = db().gaps[String(params.jobId)];
      if (!gap) return notFound("Gap analysis");
      return HttpResponse.json(gapView(store, gap));
    }),
    http.get(`${API}/gap-analyses/:gapId`, ({ params }) => {
      advance(store);
      const gap = Object.values(db().gaps).find((g) => g.id === params.gapId);
      return gap ? HttpResponse.json(gapView(store, gap)) : notFound("Gap analysis");
    }),

    // ------------------------------------------------------------ reports (R1)
    http.get(`${API}/reports`, ({ request }) => {
      advance(store);
      const query = new URL(request.url).searchParams;
      const jobFilter = query.get("job_target_id");
      const resumeFilter = query.get("resume_id");
      const typeFilter = query.get("type");
      if (typeFilter && typeFilter !== "gap_report" && typeFilter !== "interview_debrief") {
        return invalid("type must be gap_report or interview_debrief");
      }
      const jobInfo = (jobId: string) => {
        const job = findJob(jobId);
        return { job_name: job && !job.deleted ? job.name : null, job_deleted: job?.deleted ?? true };
      };
      const items: ReportItem[] = [];
      if (typeFilter !== "interview_debrief") {
        for (const gap of Object.values(db().gaps)) {
          if (gap.status !== "ready" || (jobFilter && gap.job_target_id !== jobFilter)) continue;
          if (resumeFilter && gap.resume_id !== resumeFilter) continue;
          const view = gapView(store, gap);
          items.push({
            type: "gap_report",
            id: gap.id,
            job_target_id: gap.job_target_id,
            ...jobInfo(gap.job_target_id),
            resume_id: gap.resume_id,
            resume_name: view.resume_name,
            resume_deleted: view.resume_deleted,
            status: "ready",
            at: gap.updated_at ?? gap.created_at,
            match_score: gap.analysis?.match_score ?? null,
            hire_signal: null,
            interview_type: null,
            mode: null,
            duration_min: null,
          });
        }
      }
      if (typeFilter !== "gap_report") {
        for (const s of db().sessions) {
          if (!s.started_at || !["scoring", "completed", "failed"].includes(s.status)) continue;
          if (jobFilter && s.job_target_id !== jobFilter) continue;
          if (resumeFilter && s.resume_id !== resumeFilter) continue;
          const generic = findJob(s.job_target_id)?.generic_mode ?? true;
          const cv = s.resume_id ? db().resumes.find((r) => r.id === s.resume_id) : undefined;
          items.push({
            type: "interview_debrief",
            id: s.id,
            job_target_id: s.job_target_id,
            ...jobInfo(s.job_target_id),
            resume_id: s.resume_id,
            resume_name: cv && !cv.deleted ? cv.name : null,
            resume_deleted: s.resume_id !== null && (!cv || cv.deleted),
            status: s.status === "completed" ? "ready" : s.status === "failed" ? "failed" : "scoring",
            at: s.ended_at ?? s.started_at,
            match_score: null,
            hire_signal: s.status === "completed" ? scorecardFor(s.config.interview_type, generic).hire_signal : null,
            interview_type: s.config.interview_type,
            mode: s.config.mode,
            duration_min: s.config.duration_min,
          });
        }
      }
      items.sort((a, b) => b.at.localeCompare(a.at));
      return HttpResponse.json(items);
    }),
  ];
}

// ---------------------------------------------------------------------------- sessions

export function sessionHandlers(store: MockStore) {
  const later = (factor = 1) => Date.now() + store.delayMs * factor;
  const db = () => store.db;
  const pause = () => pauseFor(store);
  const advanceAll = () => advance(store);

  const findJob = (id: unknown) => db().jobs.find((j) => j.id === id);
  const findSession = (id: unknown) => db().sessions.find((s) => s.id === id);

  return [
    // ------------------------------------------------------------ sessions (P7, P9, P10)
    http.post(`${API}/sessions`, async ({ request }) => {
      await pause();
      const body = (await request.json()) as CreateSessionRequest;
      const target = findJob(body.job_target_id);
      if (!target || target.deleted) return notFound("Job target");
      const usage = db().usage;
      // Same answer as strong_api.billing.ensure_can_start_session.
      const code: string | null = !usage.can_start_session
        ? (usage.block_code ?? "upgrade_required")
        : body.config.duration_min !== 10 && !usage.full_interviews_allowed
          ? "full_interview_requires_plan"
          : null;
      if (code) {
        const messages: Record<string, string> = {
          minutes_exhausted: "You have used this period's interview minutes.",
          upgrade_required: "You have used your free mini interviews. Subscribe to keep practicing.",
          full_interview_requires_plan: `Full interviews are part of the subscription. Free accounts get ${usage.free_interviews_total} mini interviews.`,
        };
        return HttpResponse.json(
          { detail: { code, message: messages[code], upgrade_url: "/upgrade" } },
          { status: 402 },
        );
      }
      // PR-3: a chosen CV needs a ready gap analysis with the job; else the job's latest one.
      const gap = db().gaps[body.job_target_id];
      const readyCv = gap?.status === "ready" ? gap.resume_id : null;
      if (body.resume_id && body.resume_id !== readyCv) {
        return HttpResponse.json({ detail: "Run the gap analysis for this CV and job first." }, { status: 409 });
      }
      const session: SessionRecord = {
        id: newId(),
        job_target_id: body.job_target_id,
        resume_id: body.resume_id ?? readyCv,
        config: body.config,
        channel: body.channel ?? "voice",
        brief_ready: true,
        status: "created",
        started_at: null,
        ended_at: null,
        minutes_billed: 0,
        failure_reason: null,
      };
      db().sessions.push(session);
      store.save();
      return HttpResponse.json(session, { status: 201 });
    }),
    http.get(`${API}/sessions/:sessionId`, ({ params }) => {
      advanceAll();
      const s = findSession(params.sessionId);
      return s ? HttpResponse.json(s) : notFound("Session");
    }),
    // The voice room is mocked too: the live page sees the "mock:" URL and uses src/session/mockVoice.
    http.post(`${API}/sessions/:sessionId/voice/join`, ({ params }) => {
      const s = findSession(params.sessionId);
      if (!s) return notFound("Session");
      if (s.status !== "created" && s.status !== "in_progress")
        return HttpResponse.json({ detail: "The session has ended." }, { status: 409 });
      if (s.status === "created") {
        // Like the API: the first join starts the session, and only a started one uses the free one.
        s.status = "in_progress";
        s.started_at = new Date().toISOString();
        const usage = db().usage;
        if (usage.plan === "free") usage.free_interviews_left = Math.max(0, usage.free_interviews_left - 1);
        refreshUsage(usage);
        store.save();
      }
      const join: VoiceJoin = { livekit_url: MOCK_VOICE_URL, room: `session-${s.id}`, token: "mock", identity: "candidate" };
      return HttpResponse.json(join);
    }),
    http.post(`${API}/sessions/:sessionId/end`, ({ params }) => {
      const s = findSession(params.sessionId);
      if (!s) return notFound("Session");
      if (s.status === "created") {
        // Same as the API: a session that never started is not billed or scored (BL-2).
        s.status = "failed";
        s.ended_at = new Date().toISOString();
      }
      if (s.status === "in_progress") {
        s.status = "scoring";
        s.ended_at = new Date().toISOString();
        s.minutes_billed = s.config.duration_min;
        if (db().usage.plan === "paid") db().usage.minutes_used += s.minutes_billed;
        refreshUsage(db().usage);
        db().debriefReadyAt[s.id] = later(2);
      }
      store.save();
      return HttpResponse.json(s);
    }),
    http.get(`${API}/job-targets/:jobId/sessions`, ({ params }) => {
      advanceAll();
      return HttpResponse.json(db().sessions.filter((s) => s.job_target_id === params.jobId));
    }),
  ];
}

// ---------------------------------------------------------------------------- debrief and progress (P8)

/** Mock-only trend math, so the dashboard has numbers to show. The real API computes them. */
function trendsFor(snapshots: ProgressSnapshot[]): CompetencyTrend[] {
  const by = new Map<string, ProgressSnapshot[]>();
  for (const s of [...snapshots].sort((a, b) => a.at.localeCompare(b.at))) {
    by.set(s.competency, [...(by.get(s.competency) ?? []), s]);
  }
  return [...by.values()]
    .map((points) => {
      const first = points[0].score;
      const latest = points[points.length - 1].score;
      const change = Math.round((latest - first) * 100) / 100;
      const direction: CompetencyTrend["direction"] =
        points.length === 1 ? "single" : Math.abs(change) < 0.25 ? "flat" : change > 0 ? "up" : "down";
      return {
        competency: points[0].competency,
        sessions: points.length,
        first,
        latest,
        change,
        average: Math.round((points.reduce((n, p) => n + p.score, 0) / points.length) * 100) / 100,
        direction,
      };
    })
    .sort((a, b) => a.latest - b.latest);
}

export function scoringHandlers(store: MockStore) {
  const db = () => store.db;
  const advanceAll = () => advance(store);
  const findJob = (id: unknown) => db().jobs.find((j) => j.id === id);
  const findSession = (id: unknown) => db().sessions.find((s) => s.id === id);

  const progressFor = (jobId: string): ProgressSnapshot[] => {
    // Like the API: Realistic sessions only, and never a 10-minute mini interview.
    const realistic = db().sessions.filter(
      (s) =>
        s.job_target_id === jobId &&
        s.status === "completed" &&
        s.config.mode === "realistic" &&
        s.config.duration_min !== 10,
    );
    return realistic.flatMap((s, index) =>
      scorecardFor(s.config.interview_type).competency_scores.map((c) => ({
        job_target_id: jobId,
        session_id: s.id,
        competency: c.competency,
        score: Math.min(4, Math.max(1, c.score - 0.5 + 0.25 * index)),
        at: s.ended_at ?? new Date().toISOString(),
      })),
    );
  };

  return [
    http.get(`${API}/sessions/:sessionId/debrief`, ({ params }) => {
      advanceAll();
      const s = findSession(params.sessionId);
      if (!s) return notFound("Session");
      const job = findJob(s.job_target_id);
      const generic = job?.generic_mode ?? true;
      const ready = s.status === "completed";
      const scorecard = ready ? scorecardFor(s.config.interview_type, generic) : null;
      const debrief: Debrief = {
        // The debrief's session has no channel or brief_ready (DebriefSession in openapi.json).
        session: {
          id: s.id,
          job_target_id: s.job_target_id,
          config: s.config,
          status: s.status,
          started_at: s.started_at,
          ended_at: s.ended_at,
          minutes_billed: s.minutes_billed,
          failure_reason: s.failure_reason ?? null,
        },
        status: ready
          ? "ready"
          : s.status === "failed"
            ? s.started_at === null
              ? "not_started"
              : "failed"
            : "scoring",
        scorecard,
        next_session: ready ? sessionPlan[1] : null,
        generic_mode: generic,
        company_name: job?.posting?.company_name ?? null,
        values_framework: generic ? null : "Company values",
      };
      return HttpResponse.json(debrief);
    }),
    http.get(`${API}/job-targets/:jobId/progress`, ({ params }) => {
      advanceAll();
      const jobId = String(params.jobId);
      if (!findJob(jobId)) return notFound("Job target");
      const snapshots = progressFor(jobId);
      const progress: JobProgress = {
        job_target_id: jobId,
        snapshots,
        trends: trendsFor(snapshots),
        next_session: db().gaps[jobId]?.analysis ? sessionPlan[snapshots.length ? 1 : 0] : null,
      };
      return HttpResponse.json(progress);
    }),
  ];
}

// ---------------------------------------------------------------------------- P9 billing and account

/** The API's rules for what a user may start (strong_api.billing.entitlements), for the mock. */
export function refreshUsage(usage: Usage): Usage {
  usage.minutes_left = usage.plan === "paid" ? Math.max(0, usage.minutes_cap - usage.minutes_used) : 0;
  if (usage.plan === "paid") {
    usage.block_code = usage.minutes_left > 0 ? null : "minutes_exhausted";
  } else {
    usage.block_code = usage.free_interviews_left > 0 ? null : "upgrade_required";
  }
  usage.can_start_session = usage.block_code === null;
  usage.full_interviews_allowed = usage.plan === "paid";
  return usage;
}

/** Mock plan. The real numbers come from the API config (BILLING_* settings). */
export const MOCK_PLAN = {
  name: "Strong Hire monthly",
  price_usd_month: 29,
  minutes_cap: 300,
  free_interviews: 2,
  billing_enabled: true,
};

const EXIT_REASONS = new Set([
  "got_the_job",
  "interview_over",
  "too_expensive",
  "not_helpful",
  "technical_problems",
  "missing_feature",
  "other",
]);
const GOT_JOB = new Set(["yes", "no", "still_interviewing", "prefer_not_to_say"]);

/** Mocks of the real P9 endpoints. Paths, status codes and bodies follow openapi.json. */
export function accountHandlers(store: MockStore) {
  const db = () => store.db;

  return [
    http.get(`${API}/billing/usage`, () => HttpResponse.json(refreshUsage(db().usage))),
    // Dev-only spend indicator: the mocks track no model spend, so the indicator stays hidden.
    http.get(`${API}/dev/model-usage`, () =>
      HttpResponse.json({ profile: "fake", tracked: false, today: null, month: null, rpm_limit: null }),
    ),
    http.get(`${API}/billing/plan`, () => HttpResponse.json(MOCK_PLAN)),
    http.post(`${API}/billing/checkout`, async () => {
      await pauseFor(store);
      if (db().usage.plan === "paid") {
        return HttpResponse.json(
          { detail: { code: "already_subscribed", message: "Your plan is already active." } },
          { status: 409 },
        );
      }
      // The real endpoint returns a Stripe Checkout URL, and a webhook turns the plan on.
      // The mock turns it on at once.
      const now = Date.now();
      db().usage = refreshUsage({
        ...db().usage,
        plan: "paid",
        status: "active",
        minutes_used: 0,
        minutes_cap: MOCK_PLAN.minutes_cap,
        period_start: new Date(now).toISOString(),
        period_end: new Date(now + 30 * 24 * 3600 * 1000).toISOString(),
        cancel_at_period_end: false,
        has_billing_account: true,
      });
      store.save();
      return HttpResponse.json({ url: "/?upgraded=1" });
    }),
    http.post(`${API}/billing/portal`, async ({ request }) => {
      const body = (await request.json().catch(() => null)) as { flow?: string } | null;
      if (!db().usage.has_billing_account) {
        return HttpResponse.json(
          { detail: { code: "no_billing_account", message: "You have no plan to manage." } },
          { status: 404 },
        );
      }
      // The real endpoint returns a Stripe Customer Portal URL. The mock cancels at once.
      if (body?.flow === "cancel") db().usage.cancel_at_period_end = true;
      store.save();
      return HttpResponse.json({ url: "/account" });
    }),
    http.post(`${API}/billing/exit-survey`, async ({ request }) => {
      const body = (await request.json()) as Partial<ExitSurveyIn>;
      if (!body.reason || !EXIT_REASONS.has(body.reason) || !body.got_job || !GOT_JOB.has(body.got_job)) {
        return HttpResponse.json({ detail: [{ msg: "Answer both questions" }] }, { status: 422 });
      }
      store.db.exitSurveys.push(body as ExitSurveyIn);
      store.save();
      return HttpResponse.json({ id: newId(), created_at: new Date().toISOString() }, { status: 201 });
    }),
    http.get(`${API}/account/profile`, () => {
      const email = db().auth.userEmail;
      if (!email) return HttpResponse.json({ detail: "Sign in first" }, { status: 401 });
      return HttpResponse.json(db().profiles[email] ?? EMPTY_PROFILE);
    }),
    http.put(`${API}/account/profile`, async ({ request }) => {
      const email = db().auth.userEmail;
      if (!email) return HttpResponse.json({ detail: "Sign in first" }, { status: 401 });
      const body = (await request.json()) as ProfileIn;
      const fullName = body.full_name.trim();
      const years = body.years_experience;
      if (!fullName || years < 0 || years > 50) {
        return HttpResponse.json({ detail: [{ msg: "Check the required fields." }] }, { status: 422 });
      }
      const blank = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
      const profile: Profile = {
        full_name: fullName,
        years_experience: years,
        target_level: body.target_level,
        current_title: blank(body.current_title),
        country: blank(body.country),
        time_zone: blank(body.time_zone),
        linkedin_url: blank(body.linkedin_url),
        complete: true,
      };
      db().profiles[email] = profile;
      if (db().users[email]) Object.assign(db().users[email], { full_name: fullName, profile_complete: true });
      store.save();
      return HttpResponse.json(profile);
    }),
    http.put(`${API}/account/consent`, async ({ request }) => {
      const body = (await request.json()) as { training_consent: boolean };
      const email = db().auth.userEmail;
      if (email && db().users[email]) db().users[email].training_consent = body.training_consent;
      store.save();
      return HttpResponse.json({ training_consent: body.training_consent });
    }),
    http.post(`${API}/account/export`, async () => {
      await pauseFor(store);
      const id = newId();
      db().exports[id] = {
        id,
        status: "preparing",
        requested_at: new Date().toISOString(),
        download_url: null,
        error: null,
        readyAt: Date.now() + store.delayMs,
      };
      store.save();
      const view: ExportJob = publicView(db().exports[id]);
      return HttpResponse.json(view, { status: 202 });
    }),
    http.get(`${API}/account/export/:exportId`, ({ params }) => {
      advance(store);
      const e = db().exports[String(params.exportId)];
      if (!e) return notFound("Export");
      const view: ExportJob = publicView(e);
      return HttpResponse.json(view);
    }),
    http.delete(`${API}/account`, async () => {
      await pauseFor(store);
      store.reset();
      return HttpResponse.json(
        {
          status: "deleted",
          rows_deleted: 12,
          files_pending: 0,
          files_deleted_within_hours: 24,
          backups_expire_within_days: 30,
        },
        { status: 202 },
      );
    }),
  ];
}
