/**
 * MSW request handlers. `plannedHandlers` stand in for endpoints that later workstreams build
 * (see src/api/planned.ts). `authHandlers` stand in for the real sign-in routes, for tests and
 * for running the web app with no API at all.
 *
 * Rules such as "one free interview" live here only to make the mock believable. The real rules
 * belong to the API; the web app only shows what the API returns.
 */
import { delay } from "msw";
import { http, HttpResponse } from "msw/http";

import type {
  CreateJobRequest,
  CreateSessionRequest,
  Debrief,
  JobContext,
  JobProgress,
  JobTarget,
  JobTargetSummary,
  ResumeRecord,
  SessionRecord,
} from "../api/planned";
import type { AuthState, JobPosting, ProgressSnapshot } from "../api/types";
import { newId, type MockStore } from "./db";
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

export function plannedHandlers(store: MockStore) {
  const now = () => Date.now();
  const later = (factor = 1) => now() + store.delayMs * factor;
  const db = () => store.db;
  const pause = () => (store.delayMs > 0 ? delay(150) : Promise.resolve());

  /** Moves time-based mock states forward, as background jobs would. */
  const advance = () => {
    const d = db();
    for (const job of d.jobs) {
      if (job.status === "extracting" && now() >= (d.jobReadyAt[job.id] ?? 0)) {
        job.status = "needs_confirmation";
        job.posting = { ...jobPosting, source_url: job.source_url };
        job.company = { id: "company-stripe", name: "Stripe", slug: "stripe" };
        job.level = jobPosting.level ?? null;
      }
    }
    for (const r of d.resumes) {
      if (r.status === "parsing" && now() >= (d.resumeReadyAt[r.id] ?? 0)) {
        r.status = "ready";
        r.parsed = resume;
      }
    }
    for (const gap of Object.values(d.gaps)) {
      if (gap.status === "running" && now() >= gap.readyAt) {
        gap.status = "ready";
        gap.analysis = gapAnalysis;
      }
    }
    for (const s of d.sessions) {
      if (s.status === "scoring" && now() >= (d.debriefReadyAt[s.id] ?? 0)) s.status = "completed";
    }
    for (const e of Object.values(d.exports)) {
      if (e.status === "preparing" && now() >= e.readyAt) {
        e.status = "ready";
        e.download_url = "data:application/json;charset=utf-8,%7B%22mock%22%3Atrue%7D";
      }
    }
    store.save();
  };

  const findJob = (id: unknown) => db().jobs.find((j) => j.id === id);
  const findSession = (id: unknown) => db().sessions.find((s) => s.id === id);

  const progressFor = (jobId: string): ProgressSnapshot[] => {
    const realistic = db().sessions.filter(
      (s) => s.job_target_id === jobId && s.status === "completed" && s.config.mode === "realistic",
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
    // ------------------------------------------------------------ jobs (P2)
    http.get(`${API}/jobs`, () => {
      advance();
      const summaries: JobTargetSummary[] = db().jobs.map((job) => {
        const sessions = db().sessions.filter((s) => s.job_target_id === job.id);
        const gap = db().gaps[job.id];
        return {
          job,
          match_score: gap?.analysis?.match_score ?? null,
          sessions_count: sessions.length,
          last_session_at: sessions.at(-1)?.started_at ?? null,
        };
      });
      return HttpResponse.json(summaries);
    }),
    http.post(`${API}/jobs`, async ({ request }) => {
      await pause();
      const body = (await request.json()) as CreateJobRequest;
      if (!body.source_url && !body.raw_text) {
        return HttpResponse.json({ detail: "Give a job posting URL or paste its text" }, { status: 422 });
      }
      const blocked = body.source_url?.includes("linkedin.com") ?? false;
      const job: JobTarget = {
        id: newId(),
        status: blocked ? "failed" : "extracting",
        source_url: body.source_url ?? null,
        posting: null,
        company: null,
        level: null,
        context: null,
        resume_id: null,
        error: blocked ? "LinkedIn does not allow automatic reading. Paste the job text instead." : null,
        created_at: new Date().toISOString(),
      };
      db().jobs.push(job);
      db().jobReadyAt[job.id] = later();
      store.save();
      return HttpResponse.json(job, { status: 201 });
    }),
    http.get(`${API}/jobs/:jobId`, ({ params }) => {
      advance();
      const job = findJob(params.jobId);
      return job ? HttpResponse.json(job) : notFound("Job");
    }),
    http.put(`${API}/jobs/:jobId/posting`, async ({ params, request }) => {
      const job = findJob(params.jobId);
      if (!job) return notFound("Job");
      job.posting = (await request.json()) as JobPosting;
      job.level = job.posting.level ?? null;
      job.status = "confirmed";
      store.save();
      return HttpResponse.json(job);
    }),
    http.put(`${API}/jobs/:jobId/context`, async ({ params, request }) => {
      const job = findJob(params.jobId);
      if (!job) return notFound("Job");
      job.context = (await request.json()) as JobContext;
      store.save();
      return HttpResponse.json(job);
    }),
    http.put(`${API}/jobs/:jobId/resume`, async ({ params, request }) => {
      const job = findJob(params.jobId);
      if (!job) return notFound("Job");
      job.resume_id = ((await request.json()) as { resume_id: string }).resume_id;
      store.save();
      return HttpResponse.json(job);
    }),

    // ------------------------------------------------------------ resumes (P2)
    http.get(`${API}/resumes`, () => {
      advance();
      return HttpResponse.json(db().resumes);
    }),
    http.get(`${API}/resumes/:resumeId`, ({ params }) => {
      advance();
      const r = db().resumes.find((x) => x.id === params.resumeId);
      return r ? HttpResponse.json(r) : notFound("Resume");
    }),
    http.post(`${API}/resumes`, async ({ request }) => {
      await pause();
      const form = await request.formData();
      const file = form.get("file");
      const text = form.get("text");
      if (!(file instanceof File) && !(typeof text === "string" && text.trim())) {
        return HttpResponse.json({ detail: "Upload a PDF or DOCX file, or paste the text" }, { status: 422 });
      }
      const record: ResumeRecord = {
        id: newId(),
        status: "parsing",
        file_name: file instanceof File ? file.name : null,
        parsed: null,
        error: null,
        uploaded_at: new Date().toISOString(),
      };
      db().resumes.push(record);
      db().resumeReadyAt[record.id] = later();
      store.save();
      return HttpResponse.json(record, { status: 201 });
    }),

    // ------------------------------------------------------------ gap analysis (P6)
    http.post(`${API}/jobs/:jobId/gap-analysis`, ({ params }) => {
      const job = findJob(params.jobId);
      if (!job) return notFound("Job");
      if (!job.resume_id) return HttpResponse.json({ detail: "Add a resume first" }, { status: 409 });
      db().gaps[job.id] = {
        job_target_id: job.id,
        resume_id: job.resume_id,
        status: "running",
        analysis: null,
        error: null,
        readyAt: later(1.5),
      };
      store.save();
      return HttpResponse.json(publicView(db().gaps[job.id]), { status: 202 });
    }),
    http.get(`${API}/jobs/:jobId/gap-analysis`, ({ params }) => {
      advance();
      const gap = db().gaps[String(params.jobId)];
      if (!gap) return notFound("Gap analysis");
      return HttpResponse.json(publicView(gap));
    }),

    // ------------------------------------------------------------ sessions (P7, P9, P10)
    http.post(`${API}/sessions`, async ({ request }) => {
      await pause();
      const body = (await request.json()) as CreateSessionRequest;
      if (!findJob(body.job_target_id)) return notFound("Job");
      const usage = db().usage;
      if (usage.plan === "free" && !usage.free_interview_available) {
        return HttpResponse.json(
          { detail: { code: "upgrade_required", message: "You have used your free interview." } },
          { status: 402 },
        );
      }
      if (usage.plan === "paid" && usage.minutes_used + body.config.duration_min > usage.minutes_cap) {
        return HttpResponse.json(
          { detail: { code: "minutes_exhausted", message: "Not enough minutes left this month." } },
          { status: 402 },
        );
      }
      if (usage.plan === "free") usage.free_interview_available = false;
      const session: SessionRecord = {
        id: newId(),
        job_target_id: body.job_target_id,
        config: body.config,
        status: "in_progress",
        started_at: new Date().toISOString(),
        ended_at: null,
        minutes_billed: 0,
      };
      db().sessions.push(session);
      store.save();
      return HttpResponse.json(session, { status: 201 });
    }),
    http.get(`${API}/sessions/:sessionId`, ({ params }) => {
      advance();
      const s = findSession(params.sessionId);
      return s ? HttpResponse.json(s) : notFound("Session");
    }),
    http.post(`${API}/sessions/:sessionId/end`, ({ params }) => {
      const s = findSession(params.sessionId);
      if (!s) return notFound("Session");
      if (s.status === "in_progress") {
        s.status = "scoring";
        s.ended_at = new Date().toISOString();
        s.minutes_billed = s.config.duration_min;
        if (db().usage.plan === "paid") db().usage.minutes_used += s.minutes_billed;
        db().debriefReadyAt[s.id] = later(2);
      }
      store.save();
      return HttpResponse.json(s);
    }),
    http.get(`${API}/jobs/:jobId/sessions`, ({ params }) => {
      advance();
      return HttpResponse.json(db().sessions.filter((s) => s.job_target_id === params.jobId));
    }),

    // ------------------------------------------------------------ debrief and progress (P8)
    http.get(`${API}/sessions/:sessionId/debrief`, ({ params }) => {
      advance();
      const s = findSession(params.sessionId);
      if (!s) return notFound("Session");
      const ready = s.status === "completed";
      const debrief: Debrief = {
        session: s,
        status: ready ? "ready" : "scoring",
        scorecard: ready ? scorecardFor(s.config.interview_type) : null,
        next_session: ready ? sessionPlan[1] : null,
      };
      return HttpResponse.json(debrief);
    }),
    http.get(`${API}/jobs/:jobId/progress`, ({ params }) => {
      advance();
      const jobId = String(params.jobId);
      if (!findJob(jobId)) return notFound("Job");
      const snapshots = progressFor(jobId);
      const progress: JobProgress = {
        job_target_id: jobId,
        snapshots,
        next_session: db().gaps[jobId]?.analysis ? sessionPlan[snapshots.length ? 1 : 0] : null,
      };
      return HttpResponse.json(progress);
    }),

    // ------------------------------------------------------------ billing and account (P9)
    http.get(`${API}/billing/usage`, () => HttpResponse.json(db().usage)),
    http.get(`${API}/billing/plan`, () =>
      HttpResponse.json({ name: "Strong Hire monthly", price_usd_month: 29, minutes_cap: 300 }),
    ),
    http.post(`${API}/billing/checkout`, async () => {
      await pause();
      // The real endpoint returns a Stripe Checkout URL. The mock upgrades at once.
      const end = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString();
      db().usage = { ...db().usage, plan: "paid", minutes_cap: 300, period_end: end };
      store.save();
      return HttpResponse.json({ url: "/?upgraded=1" });
    }),
    http.put(`${API}/account/consent`, async ({ request }) => {
      const body = (await request.json()) as { training_consent: boolean };
      const email = db().auth.userEmail;
      if (email && db().users[email]) db().users[email].training_consent = body.training_consent;
      store.save();
      return HttpResponse.json({ training_consent: body.training_consent });
    }),
    http.post(`${API}/account/export`, async () => {
      await pause();
      const id = newId();
      db().exports[id] = { id, status: "preparing", download_url: null, readyAt: later() };
      store.save();
      return HttpResponse.json(publicView(db().exports[id]), { status: 202 });
    }),
    http.get(`${API}/account/export/:exportId`, ({ params }) => {
      advance();
      const e = db().exports[String(params.exportId)];
      if (!e) return notFound("Export");
      return HttpResponse.json(publicView(e));
    }),
    http.delete(`${API}/account`, async () => {
      await pause();
      store.reset();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}
